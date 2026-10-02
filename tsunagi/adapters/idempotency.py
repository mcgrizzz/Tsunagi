"""
Idempotency keys (backlog 6.2b for creating notes and media, 6.64 for every
other write).

A write that outlasts op_timeout_seconds answers 503 but still runs once Anki
is free, so a client that retries creates the note or file twice. With an
`Idempotency-Key` header the first attempt's result is recorded when the
write completes (not when the HTTP wait ends), and a retry with the same key
returns that result instead of writing again, or waits for it while the
first attempt is still running.

Keys are scoped to the caller and route and kept for TTL seconds. A reused
key with a different request is refused. A first attempt that fails is
forgotten, so its retry runs again.

POST /v1/notes and POST /v1/media record their whole response (`run`). Every
other write is covered by `Journal`: the middleware opens one per request with
a key, and each step the request takes (ops.recorded: collection writes,
main-thread calls, starting a job, an export) records its result when it
ends. A retry runs the route again, and each step returns its recorded result
instead of running a second time; a job's retry gets the same job (6.74).
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
    if not entry.done.wait(ops.op_timeout()):
        raise AnkiBusyError("Write operation timed out; Anki may be busy or blocked by a "
                            "dialog. It may still complete: retry with the same Idempotency-Key")
    if entry.error is not None:
        raise entry.error
    return entry.body or {}, not new


# ----- Every other write: one journal per request with a key (backlog 6.64) -----

class _Write:
    __slots__ = ("done", "result", "error")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: Any = None
        self.error: Optional[BaseException] = None


class _Record:
    """The collection writes one keyed request made, in call order."""

    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint
        self.writes: list = []
        self.first_done = threading.Event()   # the first attempt's request ended
        self.started = time.monotonic()

    def settled(self) -> bool:
        return self.first_done.is_set() and all(w.done.is_set() for w in self.writes)


class Journal:
    """One request's view of its record; ops.collection_op_call calls `run`."""

    def __init__(self, record: _Record, retry: bool) -> None:
        self.record, self.retry, self.replayed = record, retry, False
        self._next = 0

    def run(self, start: Callable[[Callable[[Any], None], Callable[[BaseException], None]], None],
            timeout: Optional[float], rerun_if: Optional[Callable[[Any], bool]] = None) -> Any:
        """The write's result: recorded for a retry, else from `start(done, fail)`."""
        index, self._next = self._next, self._next + 1
        record = self.record
        if self.retry and index >= len(record.writes) and not record.first_done.is_set():
            # The first attempt may still reach this write; wait for it to end.
            if not record.first_done.wait(ops.op_timeout()):
                raise AnkiBusyError("The first request with this Idempotency-Key is still running; "
                                    "retry with the same key")
        with _journals.lock:
            write = record.writes[index] if index < len(record.writes) else None
            new = write is None or (write.done.is_set() and (
                write.error is not None or (rerun_if is not None and rerun_if(write.result))))
            if new:
                write = _Write()   # a failed write runs again, as without a key
                if index < len(record.writes):
                    record.writes[index] = write
                else:
                    record.writes.append(write)
        if new:
            def done(result: Any) -> None:
                write.result = result
                write.done.set()

            def fail(error: BaseException) -> None:
                write.error = error
                write.done.set()
            start(done, fail)
        limit = ops.op_timeout() if timeout is None else timeout
        if not write.done.wait(None if limit == ops.FOREVER else limit):
            raise AnkiBusyError("Write operation timed out; Anki may be busy or blocked by a "
                                "dialog. It may still complete: retry with the same Idempotency-Key")
        if write.error is not None:
            raise write.error
        self.replayed = self.replayed or not new
        return write.result


class _Journals:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._records: "OrderedDict[Tuple[str, ...], _Record]" = OrderedDict()

    def open(self, scope: Tuple[str, ...], fingerprint: str) -> Journal:
        with self.lock:
            now = time.monotonic()
            for old in [s for s, r in self._records.items() if r.settled() and now - r.started >= TTL]:
                del self._records[old]
            while len(self._records) > MAX_ENTRIES:
                oldest = next((s for s, r in self._records.items() if r.settled()), None)
                if oldest is None:
                    break
                del self._records[oldest]
            record = self._records.get(scope)
            if record is None:
                self._records[scope] = record = _Record(fingerprint)
                return Journal(record, retry=False)
        if record.fingerprint != fingerprint:
            raise ValidationError("This Idempotency-Key was already used for a different "
                                  "request; use a new key for a new request")
        return Journal(record, retry=True)

    def close(self, journal: Journal) -> None:
        if not journal.retry:
            journal.record.first_done.set()

    def reset(self) -> None:
        """Test helper."""
        with self.lock:
            self._records.clear()


_journals = _Journals()
open_journal = _journals.open
close_journal = _journals.close
