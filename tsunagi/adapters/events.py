"""
In-memory event broker feeding the SSE stream at GET /v1/events.

Cross-request state in the jobs.py/settings.py shape: a module singleton
guarded by a lock, written from the Qt main thread (gui_hooks callbacks in
the root __init__.py) and drained from the server's asyncio loop. Pure
stdlib - protobuf OpChanges objects arrive duck-typed, so this module stays
importable headless.

Delivery is best-effort and live-only: each subscriber has a bounded queue,
and a consumer that falls behind gets a `gap` replacing its incomplete
backlog on the next drain. Collection notifications describe each affected
resource with a named event, before subscriber filtering and queueing.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, FrozenSet, List, Optional
from uuid import uuid4

from .event_results import freeze_changes

MAX_QUEUED = 500  # per subscriber; beyond this the oldest events drop


CHANGE_RESOURCES = frozenset({
    "notes", "cards", "models", "decks", "tags", "reviews", "scheduler", "config",
})
DATA_EVENT_TYPES = (frozenset(f"{resource}.changed" for resource in CHANGE_RESOURCES)
                    | frozenset(f"{resource}.{kind}" for resource in ("notes", "cards")
                                for kind in ("created", "updated", "deleted")))
EVENT_TYPES = DATA_EVENT_TYPES | {"change", "review", "sync"}


def _collection_events(payload: dict, *, broad: bool = False) -> List[dict]:
    """Describe each resource once, using confirmed results where available."""
    affected = payload.get("affected")
    resources = (CHANGE_RESOURCES if broad or not affected or "collection" in affected
                 else set(affected))
    results = {} if broad else payload.get("changes", {})
    metadata = {key: payload[key] for key in ("origin", "anki") if key in payload}
    events = []
    for resource in sorted(resources | results.keys()):
        if resource in results:
            for kind, ids in results[resource].items():
                if ids:
                    events.append({**metadata, "type": f"{resource}.{kind}", "ids": ids})
        else:
            events.append({**metadata, "type": f"{resource}.changed", "ids": None,
                           "reason": "collection" if broad else "details_unavailable"})
    return events


class ApiOp:
    """
    Passed as CollectionOp's `initiator` for every Tsunagi mutation. Anki
    delivers it verbatim to operation_did_execute as `handler`, which makes
    it two things at once: the origin marker ("api") and the carrier for the
    per-op identity (note ids etc.) that OpChanges structurally lacks -
    riding through Anki itself, so there is no correlation race between
    concurrent ops. After a dev reload an in-flight op still holding the old
    module's class maps to origin "ui" - harmless.
    """
    __slots__ = ("details", "collection", "changes")

    def __init__(self, details: Optional[Dict[str, Any]] = None, *,
                 collection: Any = None) -> None:
        self.details = dict(details or {})
        self.collection = collection
        self.changes: Dict[str, Any] = {}


class _Subscriber:
    __slots__ = ("queue", "dropped", "ready", "types", "resources")

    def __init__(self, session_id: str, after_seq: int, *,
                 types: Optional[FrozenSet[str]],
                 resources: Optional[FrozenSet[str]]) -> None:
        self.types = types
        self.resources = resources
        self.queue: Deque[Dict[str, Any]] = deque(maxlen=MAX_QUEUED)
        self.dropped = 0
        # Registration and its boundary are captured under the publish lock.
        # Kept outside the bounded queue, so overflow cannot displace ready.
        self.ready = {"type": "ready", "session_id": session_id,
                      "after_seq": after_seq, "ts": int(time.time() * 1000)}

    def accepts(self, type: str) -> bool:
        is_data = type in DATA_EVENT_TYPES
        if self.types is not None and type not in self.types:
            if not (is_data and "change" in self.types):
                return False
        return (not is_data or self.resources is None
                or type.split(".", 1)[0] in self.resources)


class EventBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._subscribers: Dict[int, _Subscriber] = {}
        self._next_token = 1
        self._draining = True
        self._session_id: Optional[str] = None
        self._collection: Any = None

    def start_session(self, collection: Any) -> str:
        """Start a server/collection lifetime; old tokens stay closed forever."""
        with self._lock:
            self._subscribers.clear()
            self._session_id = uuid4().hex
            self._collection = collection
            self._seq = 0
            self._draining = False
            return self._session_id

    def subscribe(self, *, types: Optional[FrozenSet[str]] = None,
                  resources: Optional[FrozenSet[str]] = None) -> Optional[int]:
        with self._lock:
            if self._draining or self._session_id is None:
                return None
            token = self._next_token
            self._next_token += 1
            self._subscribers[token] = _Subscriber(
                self._session_id, self._seq, types=types, resources=resources)
            return token

    def ready(self, token: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            sub = self._subscribers.get(token)
            return dict(sub.ready) if sub is not None else None

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    def has_subscribers(self) -> bool:
        """Hook callbacks skip payload/undo-label work when nobody is listening."""
        with self._lock:
            return bool(self._subscribers)

    def has_change_subscribers(self) -> bool:
        """Avoid preparing changed IDs for review/sync-only listeners."""
        with self._lock:
            return any(sub.types is None or "change" in sub.types
                       or bool(sub.types & DATA_EVENT_TYPES)
                       for sub in self._subscribers.values())

    def publish(self, type: str, *, collection: Any = None, **payload: Any) -> None:
        """Fan out live events; reject a late operation from an old collection."""
        with self._lock:
            if self._draining:
                return
            if (collection is not None and self._collection is not None
                    and collection is not self._collection):
                return
            if type in ("change", "reset"):
                for event in _collection_events(payload, broad=type == "reset"):
                    self._enqueue_locked(event["type"], event)
            else:
                self._enqueue_locked(type, payload)

    def _enqueue_locked(self, type: str, payload: dict) -> None:
        self._seq += 1
        event = {**payload, "type": type, "seq": self._seq,
                 "session_id": self._session_id, "ts": int(time.time() * 1000)}
        for sub in self._subscribers.values():
            if not sub.accepts(type):
                continue
            if len(sub.queue) == sub.queue.maxlen:
                sub.dropped += 1
            sub.queue.append(event)

    def drain(self, token: int) -> List[Dict[str, Any]]:
        """Pending events, or a gap replacing the incomplete subscriber backlog."""
        with self._lock:
            sub = self._subscribers.get(token)
            if sub is None:
                return []
            events = list(sub.queue)
            sub.queue.clear()
            if sub.dropped:
                discarded = sub.dropped + len(events)
                sub.dropped = 0
                # Connection-local control: no global event ID. The boundary
                # and discard happen under the same lock as live publication.
                return [{"type": "gap", "after_seq": self._seq,
                         "session_id": self._session_id,
                         "ts": int(time.time() * 1000), "reason": "lagged",
                         "discarded": discarded}]
            return events

    def begin_drain(self, session_id: Optional[str] = None) -> None:
        """Close streams, unless this is a late shutdown from an older server."""
        with self._lock:
            if session_id is not None and session_id != self._session_id:
                return
            self._draining = True
            self._subscribers.clear()
            self._collection = None

    def is_draining(self, token: Optional[int] = None) -> bool:
        with self._lock:
            return self._draining or (token is not None and token not in self._subscribers)

    def reset(self) -> None:
        """Test helper: start an isolated, unbound session with no subscribers."""
        self.start_session(None)


# Module singleton, mirroring adapters.jobs.jobs.
broker = EventBroker()

_AFFECTED_RESOURCES = {
    # Notes, cards and reviews all accept Anki search, so a note/deck/tag
    # change can alter a review query without changing a single revlog row.
    "note": {"notes", "cards", "reviews", "tags", "models"},
    "note_text": {"notes", "cards", "reviews"},
    "card": {"cards", "notes", "reviews", "decks", "scheduler"},
    "deck": {"decks", "cards", "notes", "reviews", "scheduler"},
    "notetype": {"models", "notes", "cards", "reviews"},
    "tag": {"tags", "notes", "cards", "reviews"},
    "config": {"config", "cards", "notes", "reviews", "scheduler"},
    "deck_config": {"decks", "config", "cards", "notes", "reviews", "scheduler"},
    "study_queues": {"cards", "notes", "reviews", "scheduler"},
}
_UI_FLAGS = {"mtime", "browser_table", "browser_sidebar"}


def affected_resources(flags: List[str]) -> List[str]:
    """Conservative view invalidation, including related data and future flags."""
    resources: set[str] = set()
    for flag in flags:
        if flag in _AFFECTED_RESOURCES:
            resources.update(_AFFECTED_RESOURCES[flag])
        elif flag not in _UI_FLAGS:
            return ["collection"]
    return sorted(resources) if resources else ["collection"]


def _changed_flags(changes: Any) -> List[str]:
    """True flags of an OpChanges, by descriptor - version-proof. The "kind"
    skip mirrors Anki's own op_made_changes (defensive; no such field on
    either pinned version)."""
    return [f.name for f in changes.DESCRIPTOR.fields
            if f.name != "kind" and getattr(changes, f.name, False)]


# Ordinary UI text edits use these flags. Keep API writes, untagged undo,
# card creation/deletion, and unknown future changes visible.
_UI_TEXT_FLAGS = {"note", "note_text", "mtime", "browser_table", "browser_sidebar"}


def is_ui_text_update(changes: Any, handler: Any) -> bool:
    if handler is None or isinstance(handler, ApiOp):
        return False
    return {"note", "note_text"} <= set(_changed_flags(changes)) <= _UI_TEXT_FLAGS


def dispatch_op(changes: Any, handler: Any, label: Optional[str] = None) -> None:
    """
    Route an operation_did_execute fire to the right event:
    - every flag true + no handler is Anki's synthesized "everything may have
      changed" (legacy mw.reset(), fired after sync) -> `reset`
    - no flags true -> dropped (indistinguishable from a no-op; Tsunagi ops
      whose backend call returns no OpChanges land here)
    - otherwise -> `change`, with origin "api" for Tsunagi's own mutations.
    `label` comes from Anki's undo status. Only use it when a handler
    identifies the operation: after an untagged undo it names the next
    undoable action, not the change that just completed.
    """
    if is_ui_text_update(changes, handler):
        return
    flags = _changed_flags(changes)
    if not flags:
        return
    total = sum(1 for f in changes.DESCRIPTOR.fields if f.name != "kind")
    if handler is None and len(flags) == total:
        broker.publish("reset")
        return
    if isinstance(handler, ApiOp):
        origin: Optional[str] = "api"
    elif handler is None:
        origin = None
    else:
        origin = "ui"
    anki: dict = {"changes": flags}
    if label and handler is not None:
        anki["label"] = label
    record_changes = handler.changes if isinstance(handler, ApiOp) else {}
    broker.publish("change",
                   **({"changes": record_changes} if record_changes else {}),
                   collection=handler.collection if isinstance(handler, ApiOp) else None,
                   origin=origin, affected=affected_resources(flags),
                   anki=anki)


def publish_note_added(note_ids: List[int], changes: Any = None) -> None:
    """A confirmed Add-dialog save whose hook/response supplies the new note IDs.

    This supplements general operation notifications; it never suppresses
    them, since they may cover additional side effects.
    """
    ids = list(dict.fromkeys(int(nid) for nid in note_ids if int(nid) > 0))
    if not ids or not broker.has_subscribers():
        return
    flags = _changed_flags(changes) if changes is not None else []
    if changes is not None and not getattr(changes, "note", False):
        return
    affected = affected_resources(flags) if flags else []
    if "collection" not in affected:
        affected = sorted(set(affected) | {"notes", "cards", "tags", "models"})
    broker.publish("change", origin="ui",
                   changes=freeze_changes({"notes": {"created": ids}}),
                   affected=affected, anki={"changes": flags})


def publish_review(card_id: int, ease: int) -> None:
    broker.publish("review", card_id=card_id, ease=ease)


def publish_sync(phase: str) -> None:
    broker.publish("sync", phase=phase)
