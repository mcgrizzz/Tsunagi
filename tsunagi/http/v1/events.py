"""
The event stream: GET /v1/events as Server-Sent Events.

Hand-rolled SSE over StreamingResponse - no new dependencies, and unlike a
websocket it goes through the auth/CORS middleware like any other request.
The generator waits on an asyncio.Event that the broker sets, through
call_soon_threadsafe, whenever it queues an event for this stream or shuts
down. A 1 s ceiling on the wait also notices the caller's key or role changing.

Events are published from Qt-main-thread hook callbacks registered in the
addon root __init__.py; see adapters/events.py for the broker and the
dispatch rules.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Annotated, Any, AsyncIterator, Dict, FrozenSet, List, Optional

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from ...adapters.events import (
    ACCESS_CHANGED,
    CHANGE_RESOURCES,
    DATA_EVENT_TYPES,
    EVENT_TYPES,
    broker,
    event_permitted,
)
from ...adapters.settings import settings
from ...shared.errors import CollectionUnavailableError
from ...shared.permissions import (
    PUBLIC,
    current_caller,
    current_denial,
    permitted,
    requires,
)

router = APIRouter()

CHECK_SECONDS = 1.0  # longest wait before rechecking close reasons
HEARTBEAT_SECONDS = 15.0
_DESCRIPTION = """\
Streams named collection events as Server-Sent Events (`text/event-stream`).

Connect with `?resources=notes` for note events:

- `notes.created`: notes were added; `ids` contains their IDs.
- `notes.updated`: a note update completed; `ids` identifies the affected notes.
- `notes.deleted`: a deletion completed; these `ids` are now absent.
- `notes.stale`: notes changed, but which ones isn't known. It has no `ids`;
  reload the notes you show.

Cards use the same names with the cards prefix. Reviews report reviews.created
with review log IDs. decks.counts lists the decks whose due counts changed
(answers, suspends, deck changes, syncs, day rollover), each as {id, new_count,
learn_count, review_count, total_in_deck} like /v1/decks rows. Other resources currently report stale notifications.
No full notes, card contents or media are sent. Fetch any contents your app needs through the normal API, with select to choose fields.
A resource with complete ID details does not also emit stale for that operation.
Related resources can produce separate events: deleting a note produces
notes.deleted and cards.deleted. Each notification has its own sequence number.

### Coverage

Native and compatibility note creation/field updates provide note IDs. Native
creation also provides generated card IDs. Note deletion provides IDs now absent,
for the notes and their cards; a batch may include note IDs already absent. Individual suspend/unsuspend/bury/unbury
operations report cards.updated with their processed IDs; a batch can include
cards already in the requested state. Empty/no-op operations produce no event.
Changes made inside Anki (Browser, editor, Add dialog, reviewer) are reported
with IDs about 0.5 s after they stop, or after a 2 s pause in typing, including
reviews.created for new review log rows, and one decks.counts per burst. Undo and other operations whose rows
can't be identified use resource.stale. ID lists above 1,000 per resource
also use stale.

### Filters

- resources: comma-separated notes, cards, models, decks, tags, reviews,
  scheduler, config. Selects events about those resources, including related
  query changes (such as a deck rename affecting a note search).
- types: exact names such as notes.created, notes.updated, notes.deleted,
  notes.stale, cards.updated, cards.answered, sync. The group change selects all data
  event types. Omit both filters for all activity. Resources alone selects data
  events; types alone can select just one event, such as notes.deleted.
- Combined filters intersect for data events. cards.answered/sync can be selected alongside
  them. A combination with no matching data type returns HTTP 422, as do empty
  or unknown filter values. Filtering happens before the subscriber queue.

cards.answered is sent for answers in Anki's reviewer (origin ui) and through either API
(origin api). It contains card_id, ease (1 Again, 2 Hard, 3 Good, 4 Easy) and
the card's new interval, due, queue and memory_state, named as in card rows.
sync contains
phase started/finished. Exact type filters omit other events, including stale;
use resources alone if you need all notifications affecting a displayed list.

### Connection events

Every connection starts with ready: session_id, after_seq, ts, the selected
data resources and heartbeat_ms, how often a heartbeat comment is sent
(15000). This announces an active subscription, not a data change. Load
initial data after ready. cards.answered/sync-only subscriptions have an empty resources
list. A new connection gets a new ready even when it uses the same session.

access.changed (type and ts only) means what this app may do might have
changed: fetch /v1/capabilities again. Every stream gets it, whatever its
filters: before close with reason auth when this app's key, role or the role's
permissions change, and on an open stream when add-on actions are enabled or
disabled or FSRS is turned on or off. types=access.changed alone needs no
permission, so any accepted app can watch for it; other filters need
read:collection. The capabilities report lists what this stream would send
the app under operations["GET /v1/events"].options.

gap means queued notifications were lost (reason lagged, discarded count).
Data clients can reload their displayed queries; answer counters should mark
delivery incomplete. There is no separate refresh instruction or acknowledgement.
Broad Anki resets report resource.stale with reason collection. Other unknown
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
session and close old streams. close reports profile_closed (reconnect once
a profile is open again), shutdown, auth (the caller's key or role changed), timeout or max_events. Ready and gap do not count toward max_events. Heartbeat
comments keep idle connections alive. No active session returns HTTP 503.
Browser EventSource can use api_key when it cannot set an authentication header.

General and detailed Add-dialog notifications can overlap. Media/import coverage
is incomplete; other add-ons can bypass hooks. Optional origin/anki fields are
diagnostics, not stable identifiers for user actions. Changes made through the
API carry client, the name of the app that sent the request.
"""


def _sse_frame(event: Dict[str, Any]) -> str:
    event_id = (f"id: {event['session_id']}:{event['seq']}\n"
                if "seq" in event else "")
    return (f"event: {event['type']}\n" + event_id
            + f"data: {json.dumps(event, separators=(',', ':'))}\n\n")


def _close_frame(reason: str) -> str:
    return f"event: close\ndata: {json.dumps({'reason': reason})}\n\n"


def _closing(reason: str) -> List[str]:
    """The last frames, one per chunk. Losing access says so first, so the app
    fetches /v1/capabilities again (6.100)."""
    return ([_sse_frame(_access_changed())] if reason == "auth" else []) + [_close_frame(reason)]


def _access_changed() -> Dict[str, Any]:
    return {"type": ACCESS_CHANGED, "ts": int(time.time() * 1000)}


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
    # Any accepted app may watch for access.changed alone (6.100), as it may
    # read the capabilities report; everything else needs read:collection.
    openapi_extra=requires(PUBLIC),
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
                    "notes.stale, cards.answered, sync; change selects all data events. "
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
    if (selected_types != {ACCESS_CHANGED} or selected_resources is not None) \
            and not permitted("read:collection"):
        raise HTTPException(status_code=403, detail=current_denial("read:collection"))
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
    # Listed in `ready`: what this stream can actually receive with the
    # caller's permissions.
    caller = current_caller.get()
    data_resources = frozenset(r for r in data_resources
                               if event_permitted(caller.grants, f"{r}.stale"))
    if broker.is_draining():
        raise CollectionUnavailableError("No active event session")

    async def gen() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        woken = asyncio.Event()

        def wake() -> None:
            try:
                loop.call_soon_threadsafe(woken.set)
            except RuntimeError:  # loop already closed
                pass

        token = broker.subscribe(types=selected_types, resources=selected_resources,
                                 grants=caller.grants, wake=wake)
        if token is None:
            yield _close_frame(broker.close_reason)
            return

        approvals = settings.addon_enabled()

        def close_reason() -> Optional[str]:
            if broker.is_draining(token):
                return broker.close_reason
            # Key removed or role changed since connecting: reconnect to
            # pick up the new permissions.
            if settings.resolve_caller(caller.key, caller.local) != caller:
                return "auth"
            return None

        try:
            yield "retry: 3000\n\n: connected\n\n"
            ready = broker.ready(token)
            reason = close_reason()
            if reason or ready is None:
                for frame in _closing(reason or broker.close_reason):
                    yield frame
                return
            yield _sse_frame({**ready, "resources": sorted(data_resources),
                              "heartbeat_ms": round(HEARTBEAT_SECONDS * 1000)})
            sent = 0
            start = last_beat = time.monotonic()
            while True:
                reason = close_reason()
                if reason:
                    for frame in _closing(reason):
                        yield frame
                    return
                # Add-on actions enabled or disabled change what any app can run.
                if settings.addon_enabled() != approvals:
                    approvals = settings.addon_enabled()
                    yield _sse_frame(_access_changed())
                woken.clear()
                for event in broker.drain(token):
                    # A yield can suspend across shutdown, profile switch or
                    # key rotation. Never continue emitting a drained batch.
                    reason = close_reason()
                    if reason:
                        for frame in _closing(reason):
                            yield frame
                        return
                    yield _sse_frame(event)
                    if event["type"] in ("gap", ACCESS_CHANGED):
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
                delay = min(CHECK_SECONDS, HEARTBEAT_SECONDS - (now - last_beat))
                if timeout is not None:
                    delay = min(delay, max(0.0, timeout - (now - start)))
                try:
                    await asyncio.wait_for(woken.wait(), delay)
                except asyncio.TimeoutError:
                    pass
        finally:
            broker.unsubscribe(token)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
