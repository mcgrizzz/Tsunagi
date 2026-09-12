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

from ...adapters.events import broker
from ...adapters.settings import settings
from ...shared.errors import CollectionUnavailableError

router = APIRouter()

POLL_SECONDS = 0.25
HEARTBEAT_SECONDS = 15.0
EVENT_TYPES = frozenset({"refresh", "review", "sync"})
CHANGE_RESOURCES = frozenset({
    "notes", "cards", "models", "decks", "tags", "reviews", "scheduler", "config",
})

_DESCRIPTION = """\
Streams live notifications as Server-Sent Events (`text/event-stream`).

**Keep notes current:** connect to `/v1/events?resources=notes` and handle
`refresh` by reloading the notes your interface displays. The same handler covers
initial loading, later changes, broad Anki invalidations and gap recovery.
No separate ready/reset handler or acknowledgement is needed.

**React to reviewer answers:** use `/v1/events?types=review`. This subscription
receives no initial refresh or collection invalidations. `types=sync` similarly
selects sync progress. With neither filter, all three notification types arrive.

- `types`: comma-separated `refresh`, `review`, `sync`. If omitted with resources,
  defaults to refresh; otherwise all types. Explicit types with resources must
  include refresh. Empty/unknown values or incompatible filters return HTTP 422.
- `resources`: comma-separated views to keep current: notes, cards, models,
  decks, tags, reviews, scheduler, config. A refresh contains only subscribed
  views that may be affected. Broad/unknown changes cover all subscribed views.
  Filtering happens before the subscriber queue; unrelated traffic cannot fill it.

### Notification payloads

- `refresh`: `resources` names affected views, and `targets` contains known IDs
  within those views (possibly empty). `reason` is initial, change, collection
  (broad Anki invalidation), or recovery (after a gap). All reasons can use the
  same refresh handler; they never instruct the client to reset Anki or download
  the whole collection. Mutation details may include origin (api/ui/null), action
  (notes.created/notes.updated/collection.changed), and raw anki flags/label.
  Targets are hints, not an exhaustive change set; query membership can change.
- `review`: reviewer answer with `card_id` and `ease` (1–4).
- `sync`: `phase` is started or finished. The broad invalidation after sync goes
  only to subscribers selecting refresh.

### Connection and delivery

A refresh subscription starts with `refresh` reason initial, outside the bounded
queue. Registration and its `after_seq` boundary are captured atomically. Start
reading data on this event; changes during that read are queued. Retain a refresh
request arriving during a read and read again afterward. Discard unfinished reads
when the connection fails/closes; the next connection sends another initial
refresh, even when its session ID is unchanged. Review/sync-only streams start
with a connection comment and do not request an initial data load.

`gap` reports an overflowed subscriber queue: reason lagged, discarded notification
count, session_id, ts and after_seq. Its incomplete backlog was discarded. Data
subscribers automatically receive a scoped refresh reason recovery immediately
after the gap; their normal refresh handler is sufficient to reload current data.
Clients counting reviewer answers should treat gap as incomplete delivery, not
invent missing answers. Gap is a delivery notice, not a collection invalidation.
`close` ends the stream with reason shutdown, timeout, max_events or auth
(API key changed). Neither notice needs acknowledgement. Heartbeat comments keep
idle connections alive.

Live notifications have session_id, seq and ts (Unix milliseconds); their SSE ID
is `<session_id>:<seq>`. Filtering can leave sequence gaps. Initial/recovery refresh
and gap are connection-local boundaries with after_seq instead of seq, and no SSE
ID. Subsequent live notifications have greater seq. The same live event keeps its
ID across subscriptions, but its resources/targets are scoped to each subscriber.
Initial refresh and gap do not count toward max_events; recovery refresh does.

Server restart/profile switch creates a new session ID and closes old streams.
Delivery is best-effort and live-only: Last-Event-ID does not replay missed events,
and gap does not detect every network loss. Boundaries do not make separate HTTP
reads an atomic snapshot. No active session returns HTTP 503.

### Editing and coverage

Ordinary UI note/text notifications wait for 300 ms of quiet, with a 1-second
maximum during continuous editing (plus scheduling/network delay). Compatible
notifications merge targets; general/detailed editor actions remain distinct.
Other activity flushes pending edits first. API writes, reviews, undo/unknown
origins, known creation/deletion and broader changes bypass this debounce.
Registration flushes prior edits before its boundary. Saves and reads stay live.

Selected API mutations and supported editor/Add-dialog saves supply IDs only
after success. Undo, general UI work and sync can lack IDs. Coalesce refreshes;
notification counts are not mutation counts. Media/import coverage is incomplete,
and direct database writes by another add-on may bypass hooks.

Browser EventSource can use the api_key query parameter when custom authentication
headers are unavailable. The JSON routes' stats envelope does not apply.
"""


def _sse_frame(event: Dict[str, Any]) -> str:
    event_id = (f"id: {event['session_id']}:{event['seq']}\n"
                if "seq" in event else "")
    return (f"event: {event['type']}\n" + event_id
            + f"data: {json.dumps(event, separators=(',', ':'))}\n\n")


def _close_frame(reason: str) -> str:
    return f"event: close\ndata: {json.dumps({'reason': reason})}\n\n"


def _refresh_event(event: dict, resources: FrozenSet[str], reason: str) -> dict:
    """Present hook invalidations and connection boundaries in one client shape."""
    affected = event.get("refresh")
    selected = (resources if not affected or "collection" in affected
                else resources.intersection(affected))
    result = {key: event[key] for key in ("session_id", "seq", "after_seq", "ts")
              if key in event}
    result.update(type="refresh", reason=reason, resources=sorted(selected),
                  targets={key: ids for key, ids in event.get("targets", {}).items()
                           if key in selected})
    for key in ("origin", "action", "anki"):
        if key in event:
            result[key] = event[key]
    return result


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
                                "notifications (initial refresh and gap do not count)."),
    api_key: Optional[str] = Query(
        None, description="Alternative to the X-Api-Key header for clients "
                          "that cannot send headers (browser EventSource). "
                          "Checked by the auth middleware."),
    types: Annotated[Optional[str], Query(
        description="Notification types, comma-separated: refresh, review, sync. "
                    "Defaults to refresh when resources is supplied, otherwise all.",
    )] = None,
    resources: Annotated[Optional[str], Query(
        description="Views to keep current, comma-separated: "
                    "notes, cards, models, decks, tags, reviews, scheduler, config. "
                    "Selects refresh events unless types is explicit. "
                    "If types is supplied, it must include refresh.",
    )] = None,
) -> StreamingResponse:
    selected_types = _parse_filter(types, "types", EVENT_TYPES)
    selected_resources = _parse_filter(resources, "resources", CHANGE_RESOURCES)
    if selected_resources is not None:
        if selected_types is None:
            selected_types = frozenset({"refresh"})
        elif "refresh" not in selected_types:
            raise HTTPException(status_code=422,
                                detail="resources requires the refresh event type")
    wants_refresh = selected_types is None or "refresh" in selected_types
    refresh_resources = selected_resources or CHANGE_RESOURCES
    hook_types = (None if selected_types is None else frozenset(
        "change" if type_ == "refresh" else type_ for type_ in selected_types))
    if broker.is_draining():
        raise CollectionUnavailableError("No active event session")
    key_at_connect: str = settings.get("api_key", "")

    async def gen() -> AsyncIterator[str]:
        token = broker.subscribe(types=hook_types, resources=selected_resources)
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
            if wants_refresh:
                yield _sse_frame(_refresh_event(ready, refresh_resources, "initial"))
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
                    if event["type"] == "gap":
                        yield _sse_frame(event)
                        # A consumer may suspend after the gap across a profile
                        # switch/key rotation. Do not send an old recovery frame.
                        reason = close_reason()
                        if reason:
                            yield _close_frame(reason)
                            return
                        if not wants_refresh:
                            continue
                        event = _refresh_event(event, refresh_resources, "recovery")
                    elif event["type"] in ("change", "reset"):
                        event = _refresh_event(
                            event, refresh_resources,
                            "change" if event["type"] == "change" else "collection")
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
