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
from typing import Any, Deque, Dict, List, Optional

MAX_QUEUED = 500  # per subscriber; beyond this the oldest events drop

# Passed as CollectionOp's `initiator` for every Tsunagi mutation so op
# events can carry origin "api". After a dev reload a fresh sentinel exists;
# an op started pre-reload that lands post-reload maps to "ui" - harmless.
API_INITIATOR = object()


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

    def publish(self, type: str, **payload: Any) -> None:
        """Fan an event out to every subscriber. Non-blocking; Qt-main safe."""
        with self._lock:
            self._seq += 1
            event = {"type": type, "seq": self._seq,
                     "ts": int(time.time() * 1000), **payload}
            for sub in self._subscribers.values():
                if len(sub.queue) == sub.queue.maxlen:
                    sub.dropped += 1  # deque drops the oldest on append
                sub.queue.append(event)

    def drain(self, token: int) -> List[Dict[str, Any]]:
        """Pending events for `token`, prefixed with a lagged-reset if any
        were dropped since the last drain. Unknown token -> empty."""
        with self._lock:
            sub = self._subscribers.get(token)
            if sub is None:
                return []
            events = list(sub.queue)
            sub.queue.clear()
            if sub.dropped:
                sub.dropped = 0
                self._seq += 1
                events.insert(0, {"type": "reset", "seq": self._seq,
                                  "ts": int(time.time() * 1000),
                                  "reason": "lagged"})
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


def _changed_flags(changes: Any) -> List[str]:
    """True flags of an OpChanges, by descriptor - version-proof. The "kind"
    skip mirrors Anki's own op_made_changes (defensive; no such field on
    either pinned version)."""
    return [f.name for f in changes.DESCRIPTOR.fields
            if f.name != "kind" and getattr(changes, f.name, False)]


def dispatch_op(changes: Any, handler: Any) -> None:
    """
    Route an operation_did_execute fire to the right event:
    - every flag true + no handler is Anki's synthesized "everything may have
      changed" (legacy mw.reset(), fired after sync) -> `reset`
    - no flags true -> dropped (indistinguishable from a no-op; Tsunagi ops
      whose backend call returns no OpChanges land here)
    - otherwise -> `op`, with origin "api" for Tsunagi's own mutations.
    """
    flags = _changed_flags(changes)
    if not flags:
        return
    total = sum(1 for f in changes.DESCRIPTOR.fields if f.name != "kind")
    if handler is None and len(flags) == total:
        broker.publish("reset")
        return
    if handler is API_INITIATOR:
        origin: Optional[str] = "api"
    elif handler is None:
        origin = None
    else:
        origin = "ui"
    broker.publish("op", origin=origin, changes=flags)


def publish_review(card_id: int, ease: int) -> None:
    broker.publish("review", card_id=card_id, ease=ease)


def publish_sync(phase: str) -> None:
    broker.publish("sync", phase=phase)
