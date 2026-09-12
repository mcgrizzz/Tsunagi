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

router = APIRouter()

POLL_SECONDS = 0.25
HEARTBEAT_SECONDS = 15.0

_DESCRIPTION = """\
Streams collection notifications as Server-Sent Events (`text/event-stream`).

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

Notifications contain `seq` and `ts` (Unix milliseconds); `close` frames
carry only their reason. IDs are available for selected API mutations,
notes saved in supported Anki editor paths, and notes added in the Add dialog.
Editor IDs are captured from the operation/request and emitted only after
success. General UI actions, undo and sync may lack target IDs. Add-dialog
and newer-editor details supplement general change events; clients should
coalesce refreshes, not count notifications as distinct mutations.

Delivery is live-only and best-effort. There is no replay or collection-session
identity yet. Fetch fresh data after reconnecting; Last-Event-ID does not resume
missed notifications. Media/import coverage is incomplete, and direct database
edits by another add-on may bypass hooks. This is not an exact collection replica.

Browser EventSource cannot set custom headers; `api_key` is available as a
query parameter. The `stats` envelope used by JSON routes does not apply.
"""


def _sse_frame(event: Dict[str, Any]) -> str:
    return (f"event: {event['type']}\n"
            f"id: {event['seq']}\n"
            f"data: {json.dumps(event, separators=(',', ':'))}\n\n")


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
                                "events."),
    api_key: Optional[str] = Query(
        None, description="Alternative to the X-Api-Key header for clients "
                          "that cannot send headers (browser EventSource). "
                          "Checked by the auth middleware."),
) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        token = broker.subscribe()
        # Auth is checked by the middleware once, at connection time - but a
        # stream lives for hours. If the API key changes underneath us, the
        # connection was authorized under rules that no longer exist: close
        # it and make the client reconnect with the current key.
        key_at_connect: str = settings.get("api_key", "")
        try:
            # retry: sets the client's reconnect delay; the comment line
            # forces the response headers out through buffering proxies.
            yield "retry: 3000\n\n: connected\n\n"
            sent = 0
            start = last_beat = time.monotonic()
            while True:
                for event in broker.drain(token):
                    yield _sse_frame(event)
                    sent += 1
                    if max_events is not None and sent >= max_events:
                        yield _close_frame("max_events")
                        return
                if broker.is_draining():
                    yield _close_frame("shutdown")
                    return
                if settings.get("api_key", "") != key_at_connect:
                    yield _close_frame("auth")
                    return
                now = time.monotonic()
                if timeout is not None and now - start >= timeout:
                    yield _close_frame("timeout")
                    return
                if now - last_beat >= HEARTBEAT_SECONDS:
                    yield ": ping\n\n"
                    last_beat = now
                await asyncio.sleep(POLL_SECONDS)
        finally:
            broker.unsubscribe(token)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
