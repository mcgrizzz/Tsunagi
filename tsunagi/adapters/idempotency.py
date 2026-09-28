"""
Idempotency keys for creating notes and media (backlog 6.2b).

A write that outlasts op_timeout_seconds answers 503 but still runs once Anki
is free, so a client that retries creates the note or file twice. With an
`Idempotency-Key` header the first attempt's result is recorded when the
write completes (not when the HTTP wait ends), and a retry with the same key
returns that result instead of writing again, or waits for it while the
first attempt is still running.

Keys are scoped to the caller and route and kept for TTL seconds. A reused
key with a different request is refused. A first attempt that fails is
forgotten, so its retry runs again.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple

from ..shared.errors import AnkiBusyError, ValidationError
from . import ops

TTL = 600.0        # seconds a key is remembered after its request started
MAX_ENTRIES = 1000


class _Entry:
    __slots__ = ("fingerprint", "done", "body", "error", "started")

    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint
        self.done = threading.Event()
        self.body: Optional[Dict[str, Any]] = None
        self.error: Optional[BaseException] = None
        self.started = time.monotonic()


class IdempotencyStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: "OrderedDict[Tuple[str, ...], _Entry]" = OrderedDict()

    def _expire(self, now: float) -> None:
        """Forget finished keys past TTL, then the oldest finished beyond
        MAX_ENTRIES. A write still running is never forgotten."""
        for scope in [s for s, e in self._entries.items()
                      if e.done.is_set() and now - e.started >= TTL]:
            del self._entries[scope]
        while len(self._entries) > MAX_ENTRIES:
            oldest = next((s for s, e in self._entries.items() if e.done.is_set()), None)
            if oldest is None:
                return
            del self._entries[oldest]

    def begin(self, scope: Tuple[str, ...], fingerprint: str) -> Tuple[_Entry, bool]:
        """(entry, True) for a new key; (existing entry, False) for a retry."""
        with self._lock:
            self._expire(time.monotonic())
            entry = self._entries.get(scope)
            if entry is not None:
                if entry.fingerprint != fingerprint:
                    raise ValidationError("This Idempotency-Key was already used for a different "
                                          "request; use a new key for a new request")
                return entry, False
            entry = self._entries[scope] = _Entry(fingerprint)
            return entry, True

    def complete(self, entry: _Entry, body: Dict[str, Any]) -> None:
        entry.body = body
        entry.done.set()

    def fail(self, scope: Tuple[str, ...], entry: _Entry, error: BaseException) -> None:
        with self._lock:
            if self._entries.get(scope) is entry:
                del self._entries[scope]  # a retry runs the write again
        entry.error = error
        entry.done.set()

    def reset(self) -> None:
        """Test helper."""
        with self._lock:
            self._entries.clear()


store = IdempotencyStore()


def scope(route: str, key: str) -> Tuple[str, ...]:
    """Keys belong to the app that sent them (or its No key row)."""
    from ..shared.permissions import current_caller
    caller = current_caller.get()
    return (caller.name if caller else "", route, key)


def fingerprint(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def run(scope: Tuple[str, ...], request_fingerprint: str,
        start: Callable[[Callable[[Dict[str, Any]], None], Callable[[BaseException], None]], None]
        ) -> Tuple[Dict[str, Any], bool]:
    """
    (response body, replayed). `start(done, fail)` begins the write and must
    call exactly one of them when it ends, however late. Waits op_timeout_seconds
    like any write; past that, 503 while the write carries on.
    """
    entry, new = store.begin(scope, request_fingerprint)
    if new:
        try:
            start(lambda body: store.complete(entry, body),
                  lambda error: store.fail(scope, entry, error))
        except BaseException as exc:
            store.fail(scope, entry, exc)
            raise
    if not entry.done.wait(ops.OP_TIMEOUT):
        raise AnkiBusyError("Write operation timed out; Anki may be busy or blocked by a "
                            "dialog. It may still complete: retry with the same Idempotency-Key")
    if entry.error is not None:
        raise entry.error
    return entry.body or {}, not new
