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
from typing import Annotated, Any, AsyncIterator, Dict, FrozenSet, Optional

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from ...adapters.events import CHANGE_RESOURCES, DATA_EVENT_TYPES, EVENT_TYPES, broker
from ...adapters.settings import settings
from ...shared.errors import CollectionUnavailableError

router = APIRouter()

POLL_SECONDS = 0.25
HEARTBEAT_SECONDS = 15.0
_DESCRIPTION = """\
Streams named collection events as Server-Sent Events (`text/event-stream`).

Connect with `?resources=notes` for note events:

- `notes.created`: notes were added; `ids` contains their IDs.
- `notes.updated`: a note update completed; `ids` identifies the affected notes.
- `notes.deleted`: a deletion completed; these `ids` are now absent.
- `notes.changed`: note data or note query results may have changed, but the
  affected IDs or kind of change aren't known. `ids` is null.

Cards use the same names with the cards prefix. Other resources currently report
changed notifications. No full notes, card contents or media are sent. Fetch any
contents your app needs through the normal API, with select to choose fields.
A resource with complete ID details does not also emit changed for that operation.
Related resources can produce separate events: deleting a note can produce
notes.deleted and cards.changed. Each notification has its own sequence number.

### Coverage

Native and compatibility note creation/field updates provide note IDs. Native
creation also provides generated card IDs. Note deletion provides IDs now absent;
a batch may include IDs already absent. Individual suspend/unsuspend/bury/unbury
operations report cards.updated with their processed IDs; a batch can include
cards already in the requested state. Empty/no-op operations produce no event.
Add-dialog saves report notes.created. Other operations use resource.changed
when details aren't known. ID lists above 1,000 per resource also use changed.

Text-only note edits inside Anki, including typing, are excluded. No delayed
finished-typing notification is sent. API edits, undo and UI changes affecting
other data are still reported. Anki's actual saves are unaffected.

### Filters

- resources: comma-separated notes, cards, models, decks, tags, reviews,
  scheduler, config. Selects events about those resources, including related
  query changes (such as a deck rename affecting a note search).
- types: exact names such as notes.created, notes.updated, notes.deleted,
  notes.changed, cards.updated, review, sync. The group change selects all data
  event types. Omit both filters for all activity. Resources alone selects data
  events; types alone can select just one event, such as notes.deleted.
- Combined filters intersect for data events. Review/sync can be selected alongside
  them. A combination with no matching data type returns HTTP 422, as do empty
  or unknown filter values. Filtering happens before the subscriber queue.

review contains card_id and ease (1 Again, 2 Hard, 3 Good, 4 Easy). sync contains
phase started/finished. Exact type filters omit other events, including changed;
use resources alone if you need all notifications affecting a displayed list.

### Connection events

Every connection starts with ready: session_id, after_seq, ts and the selected
data resources. This announces an active subscription, not a data change. Load
initial data after ready. Review/sync-only subscriptions have an empty resources
list. A new connection gets a new ready even when it uses the same session.

gap means queued notifications were lost (reason lagged, discarded count).
Data clients can reload their displayed queries; answer counters should mark
delivery incomplete. There is no separate refresh instruction or acknowledgement.
Broad Anki resets report resource.changed with reason collection. Other unknown
changes use reason details_unavailable. No whole-collection download is required.

### Ordering and connections

Live events carry session_id, seq and ts (Unix milliseconds); SSE ID is
<session_id>:<seq>. Ready and gap carry after_seq and no SSE ID. Registration
and the ready boundary are atomic; queued live events have larger seq. Filtering
can leave normal sequence gaps. One operation can emit several named events.

HTTP reads return current data, not historical snapshots. Coordinate overlapping
reads so an older response cannot overwrite a newer one. Repeat filtered queries
when membership, sorting or counts might change. Ignore unfinished loads after
disconnecting.

Delivery is best-effort and live-only: Last-Event-ID does not replay events.
Reload relevant data after reconnecting. Restarts/profile switches create a new
session and close old streams. close reports shutdown, auth (API key changed),
timeout or max_events. Ready and gap do not count toward max_events. Heartbeat
comments keep idle connections alive. No active session returns HTTP 503.
Browser EventSource can use api_key when it cannot set an authentication header.

General and detailed Add-dialog notifications can overlap. Media/import coverage
is incomplete; other add-ons can bypass hooks. Optional origin/anki fields are
diagnostics, not stable identifiers for user actions.
"""


def _sse_frame(event: Dict[str, Any]) -> str:
    event_id = (f"id: {event['session_id']}:{event['seq']}\n"
                if "seq" in event else "")
    return (f"event: {event['type']}\n" + event_id
            + f"data: {json.dumps(event, separators=(',', ':'))}\n\n")


def _close_frame(reason: str) -> str:
    return f"event: close\ndata: {json.dumps({'reason': reason})}\n\n"


def _parse_filter(value: Optional[str], name: str,
                  allowed: FrozenSet[str]) -> Optional[FrozenSet[str]]:
    if value is None:
        return None
    selected = frozenset(part.strip() for part in value.split(","))
    if not selected <= allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{name} must be a non-empty comma-separated list of: "
                   + ", ".join(sorted(allowed)),
        )
    return selected


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
                                "notifications (ready and gap do not count)."),
    api_key: Optional[str] = Query(
        None, description="Alternative to the X-Api-Key header for clients "
                          "that cannot send headers (browser EventSource). "
                          "Checked by the auth middleware."),
    types: Annotated[Optional[str], Query(
        description="Comma-separated event names, such as notes.updated, notes.deleted, "
                    "notes.changed, review, sync; change selects all data events. "
                    "Defaults to change when resources is supplied, otherwise all.",
    )] = None,
    resources: Annotated[Optional[str], Query(
        description="Views to keep current, comma-separated: "
                    "notes, cards, models, decks, tags, reviews, scheduler, config. "
                    "Selects changes unless types is explicit. "
                    "Combined types must match at least one selected data resource.",
    )] = None,
) -> StreamingResponse:
    selected_types = _parse_filter(types, "types", EVENT_TYPES)
    selected_resources = _parse_filter(resources, "resources", CHANGE_RESOURCES)
    if selected_resources is not None and selected_types is None:
        selected_types = frozenset({"change"})
    data_types = (DATA_EVENT_TYPES if selected_types is None or "change" in selected_types
                  else selected_types & DATA_EVENT_TYPES)
    data_resources = frozenset(name.split(".", 1)[0] for name in data_types)
    if selected_resources is not None:
        data_resources &= selected_resources
        if not data_resources:
            raise HTTPException(status_code=422,
                                detail="types must match at least one selected data resource")
    if broker.is_draining():
        raise CollectionUnavailableError("No active event session")
    key_at_connect: str = settings.get("api_key", "")

    async def gen() -> AsyncIterator[str]:
        token = broker.subscribe(types=selected_types, resources=selected_resources)
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
            yield _sse_frame({**ready, "resources": sorted(data_resources)})
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
                    if event["type"] == "gap":
                        continue
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
