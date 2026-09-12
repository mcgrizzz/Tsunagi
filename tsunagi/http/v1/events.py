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
EVENT_TYPES = frozenset({"change", "refresh", "review", "sync"})
CHANGE_RESOURCES = frozenset({
    "notes", "cards", "models", "decks", "tags", "reviews", "scheduler", "config",
})

_DESCRIPTION = """\
Streams live collection changes as Server-Sent Events (`text/event-stream`).

Connect with `?resources=notes` to receive saved notes directly when available.
Handle `change.changes.notes.upsert` by inserting/replacing complete native note
records, `fetch` by reading those IDs, and `remove` by removing IDs now absent.
The same keys apply under `changes.cards`. `change.refresh` lists subscribed
resources whose affected records could not be fully identified. Reload the
views you display for those resources. Input/context `targets` are only hints,
not confirmed changes or deletion instructions.

### Coverage

Native note creation/patch supplies the existing save response. Native creation
also supplies generated card IDs to fetch. Compatibility note creation/field
updates supply saved note IDs; note deletion supplies IDs now absent. Card
suspend/unsuspend/bury/unbury supply IDs to fetch. Supported editor/Add saves
supply saved note IDs, after typing debounce. Other changes use scoped refresh.
Related resources may still need refreshing even when a note record is included.
A fetch ID can be unchanged or missing; reconcile missing IDs with your store.
Native saves read back the persisted note once to include backend normalization.
Events share that result without per-subscriber reads or card rendering. Snapshots
exceeding 64 KiB become fetches; over 1,000 IDs per resource falls back to refresh.

### Filters

- `resources`: comma-separated notes, cards, models, decks, tags, reviews,
  scheduler, config. Defaults to collection changes for just those resources.
- `types`: comma-separated change, refresh, review, sync. `change` selects the
  record-aware form; `refresh` alone selects invalidations without records.
  Selecting both delivers each change once, in the richer form. Combining types
  with resources requires change or refresh. Omit both filters for all activity.
  Empty/unknown/incompatible values return HTTP 422.
- Filtering occurs before the subscriber queue. Related changes still count:
  for example, a deck rename can affect note queries using Anki search.

`review` contains card_id and ease (1 Again, 2 Hard, 3 Good, 4 Easy). `sync`
contains phase started/finished. Review/sync-only streams don't request data loads.

### Initial load and recovery

Data subscriptions start with `refresh` reason initial. Broad Anki invalidations
use reason collection. Queue overflow discards the incomplete backlog and emits
`gap` (reason lagged, discarded count), followed by scoped `refresh` reason
recovery. The same refresh handler can reload your displayed view in each case;
no reset acknowledgement or whole-collection download is required. Review/sync-only
streams receive gap without refresh: answer counters must mark delivery incomplete.
The invalidation-only mode also uses refresh reason change for ordinary mutations.

### Ordering and connections

Apply records in stream order. Coordinate asynchronous HTTP loads so an older
response cannot overwrite newer events: if a change arrives during a load, mark
the view dirty and re-read afterward. Discard outstanding loads on disconnect.
Re-evaluate filtered queries/pages when membership, sorting or counts may change:
record coverage does not imply query membership stayed the same.

Live events carry session_id, seq, ts (Unix milliseconds); SSE ID is
`<session_id>:<seq>`. Initial/recovery refreshes and gaps instead carry after_seq
and no SSE ID. Registration and the initial boundary are atomic; subsequent live
events have larger seq. Filtering can leave normal sequence gaps. Separate HTTP
reads are not atomic snapshots. Event IDs are shared, payloads scoped by resource.

Delivery is best-effort and live-only: Last-Event-ID does not replay events.
Reconnects always receive an initial refresh. Server restarts/profile switches
create a new session and close old streams. `close` reports shutdown, auth (API
key changed), timeout or max_events. Initial refresh and gap don't count toward
max_events; recovery refresh does. Heartbeat comments keep idle connections alive.
No active session returns HTTP 503. Browser EventSource may use api_key when it
cannot set an authentication header.

Ordinary saved-editor notifications wait for 300 ms of quiet, with a 1-second
maximum during continuous typing. Other activity flushes pending edits first.
API writes bypass debounce. General/detailed UI notifications can overlap;
notification counts are not mutation counts. Undo/general UI/sync may lack IDs,
media/import coverage is incomplete, and direct database writes by other add-ons
may bypass hooks. Optional origin/action/anki fields are diagnostics.
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


def _change_event(event: dict, resources: FrozenSet[str]) -> dict:
    """Apply known record changes; invalidate only the uncovered resources."""
    result = _refresh_event(event, resources, "change")
    selected = set(result["resources"])
    changes = {key: value for key, value in event.get("changes", {}).items()
               if key in selected}
    # Saved-editor hooks report real note IDs after success. Project them here,
    # after the broker has coalesced typing notifications, without reading Anki.
    if ("notes" in selected and "notes" not in changes
            and event.get("origin") == "ui"
            and event.get("action") in {"notes.created", "notes.updated"}
            and event.get("targets", {}).get("notes")):
        changes["notes"] = {"upsert": [], "fetch": event["targets"]["notes"], "remove": []}
    result.update(type="change", changes=changes,
                  refresh=sorted(selected.difference(changes)))
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
        description="Notification types, comma-separated: change, refresh, review, sync. "
                    "Defaults to change when resources is supplied, otherwise all.",
    )] = None,
    resources: Annotated[Optional[str], Query(
        description="Views to keep current, comma-separated: "
                    "notes, cards, models, decks, tags, reviews, scheduler, config. "
                    "Selects changes unless types is explicit. "
                    "If types is supplied, it must include change or refresh.",
    )] = None,
) -> StreamingResponse:
    selected_types = _parse_filter(types, "types", EVENT_TYPES)
    selected_resources = _parse_filter(resources, "resources", CHANGE_RESOURCES)
    if selected_resources is not None:
        if selected_types is None:
            selected_types = frozenset({"change"})
        elif not selected_types.intersection({"change", "refresh"}):
            raise HTTPException(status_code=422,
                                detail="resources requires the change or refresh event type")
    wants_changes = selected_types is None or "change" in selected_types
    wants_refresh = wants_changes or "refresh" in selected_types
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
                    elif event["type"] == "change" and wants_changes:
                        event = _change_event(event, refresh_resources)
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
