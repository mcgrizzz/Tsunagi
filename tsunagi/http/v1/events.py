"""
The event stream: GET /v1/events as Server-Sent Events.

Hand-rolled SSE over StreamingResponse - no new dependencies, and unlike a
websocket it goes through the auth/CORS middleware like any other request.
The generator polls the broker's thread-safe queue with a short sleep, so no
event-loop capture is needed (it behaves identically under uvicorn's loop
and the TestClient's).

Events are published from Qt-main-thread hook callbacks registered in the
addon root __init__.py; see adapters/events.py for the broker and the
dispatch rules.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Query
from starlette.responses import StreamingResponse

from ...adapters.events import broker
from ...adapters.settings import settings
from ...shared.errors import CollectionUnavailableError

router = APIRouter()

POLL_SECONDS = 0.25
HEARTBEAT_SECONDS = 15.0

_DESCRIPTION = """\
Streams collection notifications as Server-Sent Events (`text/event-stream`).

- `ready`: first named event on each connection, with `session_id`,
  `after_seq` and `refresh: ["collection"]`. Wait for it before fetching initial
  data; retain notifications received during that fetch and refresh as needed.
  It has no SSE ID and does not count toward `max_events`.
- `change`: a completed mutation. `action` is `notes.created` or
  `notes.updated` for identified UI saves, otherwise `collection.changed`.
  `origin` is `api`, `ui`, or null when unknown. `targets` groups known IDs
  by resource, e.g. `{"notes": [42]}`. These are hints, not an exhaustive
  changed-record list. `refresh` names views that may need refreshing
  (`notes`, `cards`, `models`, `decks`, `tags`, `reviews`, `scheduler`,
  `config`, or `collection` for a broad refresh). Inspect `refresh` even
  when targets are present: related records and query membership may change.
  `anki.changes` preserves Anki's raw flags; optional `anki.label` is
  localized display text, never an action identifier.
- `review`: a reviewer answer, with `card_id` and `ease` (1–4). Also followed
  by a general change notification.
- `sync`: `phase` is `started` or `finished`; finished sync is followed by reset.
- `reset`: `refresh: ["collection"]` requests a broad refresh.
  `reason: "lagged"` means an overflowed queue was replaced by this reset.
- `close`: the stream ends with `reason` equal to `shutdown`, `timeout`,
  `max_events`, or `auth` (API key changed; reconnect using the current key).

Notifications contain `session_id`, `seq` and `ts` (Unix milliseconds); their
SSE ID is `<session_id>:<seq>`. `close` frames carry only their reason. IDs are
available for selected API mutations,
notes saved in supported Anki editor paths, and notes added in the Add dialog.
Editor IDs are captured from the operation/request and emitted only after
success. General UI actions, undo and sync may lack target IDs. Add-dialog
and newer-editor details supplement general change events; clients should
coalesce refreshes, not count notifications as distinct mutations.

Ordinary UI note/text edits are debounced for 300 ms of quiet, with a 1-second
maximum during continuous editing (delivery is subject to scheduling/network
delay). Matching actions/Anki metadata combine target IDs and refresh hints.
General and detailed editor notifications stay distinct. Other activity flushes
pending edits first; API writes, reviews, undo/unknown origins, known
creation/deletion and changes affecting other resources bypass this debounce.
A new subscription also flushes prior edits before its ready boundary. An input
limit may flush large bursts early. Anki saves and reads are not delayed.

Registration and `ready.after_seq` are captured atomically; queued notifications
have greater sequence numbers. A server restart or profile switch creates a new
random session ID and closes old subscriptions. Reconnecting to the same running
server keeps the ID, but always requires a fresh read: delivery is live-only and
best-effort, and Last-Event-ID does not resume missed notifications. Discard an
unfinished initial load if the stream closes; begin again after the next ready.
No active session returns HTTP 503. This boundary is not a collection snapshot.
Media/import coverage is incomplete, and direct database edits by another add-on
may bypass hooks. This is not an exact collection replica.

Browser EventSource cannot set custom headers; `api_key` is available as a
query parameter. The `stats` envelope used by JSON routes does not apply.
"""


def _sse_frame(event: Dict[str, Any]) -> str:
    event_id = (f"id: {event['session_id']}:{event['seq']}\n"
                if "seq" in event else "")
    return (f"event: {event['type']}\n" + event_id
            + f"data: {json.dumps(event, separators=(',', ':'))}\n\n")


def _close_frame(reason: str) -> str:
    return f"event: close\ndata: {json.dumps({'reason': reason})}\n\n"


@router.get(
    "/v1/events",
    response_model=None,
    responses={200: {"content": {"text/event-stream": {}},
                     "description": "An SSE stream of collection events."}},
    summary="Stream collection events",
    description=_DESCRIPTION,
    tags=["Events"],
    operation_id="streamEvents",
)
def stream_events(
    timeout: Optional[float] = Query(
        None, gt=0, description="Close the stream cleanly after this many "
                                "seconds (for scripts and polling clients)."),
    max_events: Optional[int] = Query(
        None, gt=0, description="Close the stream cleanly after this many "
                                "notifications (ready does not count)."),
    api_key: Optional[str] = Query(
        None, description="Alternative to the X-Api-Key header for clients "
                          "that cannot send headers (browser EventSource). "
                          "Checked by the auth middleware."),
) -> StreamingResponse:
    if broker.is_draining():
        raise CollectionUnavailableError("No active event session")
    key_at_connect: str = settings.get("api_key", "")

    async def gen() -> AsyncIterator[str]:
        token = broker.subscribe()
        if token is None:
            yield _close_frame("shutdown")
            return

        def close_reason() -> Optional[str]:
            if broker.is_draining(token):
                return "shutdown"
            if settings.get("api_key", "") != key_at_connect:
                return "auth"
            return None

        try:
            yield "retry: 3000\n\n: connected\n\n"
            ready = broker.ready(token)
            reason = close_reason()
            if reason or ready is None:
                yield _close_frame(reason or "shutdown")
                return
            yield _sse_frame(ready)
            sent = 0
            start = last_beat = time.monotonic()
            while True:
                reason = close_reason()
                if reason:
                    yield _close_frame(reason)
                    return
                for event in broker.drain(token):
                    # A yield can suspend across shutdown, profile switch or
                    # key rotation. Never continue emitting a drained batch.
                    reason = close_reason()
                    if reason:
                        yield _close_frame(reason)
                        return
                    yield _sse_frame(event)
                    sent += 1
                    if max_events is not None and sent >= max_events:
                        yield _close_frame("max_events")
                        return
                now = time.monotonic()
                if timeout is not None and now - start >= timeout:
                    yield _close_frame("timeout")
                    return
                if now - last_beat >= HEARTBEAT_SECONDS:
                    yield ": ping\n\n"
                    last_beat = now
                delay = POLL_SECONDS
                edit_delay = broker.seconds_until_edit_flush(token)
                if edit_delay is not None:
                    delay = min(delay, edit_delay)
                if timeout is not None:
                    delay = min(delay, max(0.0, timeout - (now - start)))
                await asyncio.sleep(delay)
        finally:
            broker.unsubscribe(token)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
