"""
In-memory event broker feeding the SSE stream at GET /v1/events.

Cross-request state in the jobs.py/settings.py shape: a module singleton
guarded by a lock, written from the Qt main thread (gui_hooks callbacks in
the root __init__.py) and drained from the server's asyncio loop. Pure
stdlib - protobuf OpChanges objects arrive duck-typed, so this module stays
importable headless.

Delivery is best-effort and live-only: each subscriber has a bounded queue,
and a consumer that falls behind gets its oldest events dropped and a
synthetic `reset {"reason": "lagged"}` on its next drain - clients must
already handle `reset` (Anki fires it after sync and legacy mw.reset()), so
overflow introduces no new failure mode.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Deque, Dict, List, Optional

MAX_QUEUED = 500  # per subscriber; beyond this the oldest events drop

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
    __slots__ = ("details",)

    def __init__(self, details: Optional[Dict[str, Any]] = None) -> None:
        self.details = dict(details or {})


class _Subscriber:
    __slots__ = ("queue", "dropped")

    def __init__(self) -> None:
        self.queue: Deque[Dict[str, Any]] = deque(maxlen=MAX_QUEUED)
        self.dropped = 0


class EventBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._subscribers: Dict[int, _Subscriber] = {}
        self._next_token = 1
        self._draining = False

    def subscribe(self) -> int:
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._subscribers[token] = _Subscriber()
            return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    def has_subscribers(self) -> bool:
        """Hook callbacks (Qt main thread) check this first so a session
        with no stream open pays one lock acquisition per op and nothing
        else - not even the undo_status() label fetch."""
        with self._lock:
            return bool(self._subscribers)

    def publish(self, type: str, **payload: Any) -> None:
        """Fan an event out to every subscriber. Non-blocking; Qt-main safe."""
        if type == "reset":
            payload["refresh"] = ["collection"]
        with self._lock:
            self._seq += 1
            # Broker-owned keys last so no payload (e.g. attached op details)
            # can clobber them.
            event = {**payload, "type": type, "seq": self._seq,
                     "ts": int(time.time() * 1000)}
            for sub in self._subscribers.values():
                if len(sub.queue) == sub.queue.maxlen:
                    sub.dropped += 1  # deque drops the oldest on append
                sub.queue.append(event)

    def drain(self, token: int) -> List[Dict[str, Any]]:
        """Pending events, or a reset replacing a queue with a delivery gap."""
        with self._lock:
            sub = self._subscribers.get(token)
            if sub is None:
                return []
            events = list(sub.queue)
            sub.queue.clear()
            if sub.dropped:
                sub.dropped = 0
                self._seq += 1
                # Partial history is no longer sufficient. Do not put older
                # sequence IDs after this reset; start fresh at this boundary.
                return [{"type": "reset", "seq": self._seq,
                         "ts": int(time.time() * 1000), "reason": "lagged",
                         "refresh": ["collection"]}]
            return events

    # Server shutdown: stream generators poll is_draining() and close, which
    # is what lets stop_server's join(5) succeed with streams open.
    def begin_drain(self) -> None:
        with self._lock:
            self._draining = True

    def end_drain(self) -> None:
        with self._lock:
            self._draining = False

    def is_draining(self) -> bool:
        with self._lock:
            return self._draining

    def reset(self) -> None:
        """Test helper - drop everything."""
        with self._lock:
            self._seq = 0
            self._subscribers.clear()
            self._next_token = 1
            self._draining = False


# Module singleton, mirroring adapters.jobs.jobs.
broker = EventBroker()

# Only populated while one specific, successful UI completion callback runs.
# Match its exact OpChanges object, so nested/unrelated operations cannot
# inherit the edited note's identity.
_ui_change: ContextVar[Any] = ContextVar("tsunagi_ui_change", default=None)


@contextmanager
def ui_change_context(changes: Any, action: str, note_ids: List[int]):
    token = _ui_change.set((changes, action, tuple(note_ids)))
    try:
        yield
    finally:
        _ui_change.reset(token)


_REFRESH = {
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


def refresh_resources(flags: List[str]) -> List[str]:
    """Conservative view invalidation, including related data and future flags."""
    resources: set[str] = set()
    for flag in flags:
        if flag in _REFRESH:
            resources.update(_REFRESH[flag])
        elif flag not in _UI_FLAGS:
            return ["collection"]
    return sorted(resources) if resources else ["collection"]


def _targets(details: dict) -> dict:
    return {resource: list(dict.fromkeys(details[key]))
            for key, resource in (("note_ids", "notes"), ("card_ids", "cards"),
                                  ("deck_ids", "decks"), ("model_ids", "models"))
            if details.get(key)}


def _changed_flags(changes: Any) -> List[str]:
    """True flags of an OpChanges, by descriptor - version-proof. The "kind"
    skip mirrors Anki's own op_made_changes (defensive; no such field on
    either pinned version)."""
    return [f.name for f in changes.DESCRIPTOR.fields
            if f.name != "kind" and getattr(changes, f.name, False)]


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
    details = handler.details if isinstance(handler, ApiOp) else {}
    action = "collection.changed"
    ui = _ui_change.get()
    if not isinstance(handler, ApiOp) and ui is not None and ui[0] is changes:
        origin = "ui"
        action = ui[1]
        details = {"note_ids": ui[2]}
    anki: dict = {"changes": flags}
    if label and handler is not None:
        anki["label"] = label
    broker.publish("change", origin=origin, action=action,
                   targets=_targets(details), refresh=refresh_resources(flags),
                   anki=anki)


def publish_note_change(note_ids: List[int], action: str,
                        changes: Any = None) -> None:
    """A confirmed UI save whose own hook/response supplies the note IDs.

    This supplements general operation notifications; it never suppresses
    them, since they may cover additional side effects.
    """
    ids = list(dict.fromkeys(int(nid) for nid in note_ids if int(nid) > 0))
    if not ids or not broker.has_subscribers():
        return
    flags = _changed_flags(changes) if changes is not None else []
    if changes is not None and not getattr(changes, "note", False):
        return
    refresh = refresh_resources(flags) if flags else []
    if "collection" not in refresh:
        refresh = sorted(set(refresh) | {"notes", "cards", "tags", "models"})
    broker.publish("change", origin="ui", action=action, targets={"notes": ids},
                   refresh=refresh, anki={"changes": flags})


def publish_review(card_id: int, ease: int) -> None:
    broker.publish("review", card_id=card_id, ease=ease)


def publish_sync(phase: str) -> None:
    broker.publish("sync", phase=phase)
