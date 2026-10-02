"""Cross-thread waits: the default deadline, and FOREVER for long work (7.7a)."""
import threading

import pytest

from tsunagi.adapters import ops
from tsunagi.shared.errors import AnkiBusyError


def later(seconds):
    done = threading.Event()
    threading.Timer(seconds, done.set).start()
    return done


def test_default_deadline_is_op_timeout(monkeypatch):
    monkeypatch.setattr(ops, "op_timeout", lambda: 0.05)
    with pytest.raises(AnkiBusyError, match="Sync timed out"):
        ops._wait(later(0.5), {}, None, "Sync")


def test_forever_outlasts_op_timeout(monkeypatch):
    # A sync longer than op_timeout_seconds used to answer 503 while it ran on.
    monkeypatch.setattr(ops, "op_timeout", lambda: 0.05)
    assert ops._wait(later(0.3), {"result": "synced"}, ops.FOREVER, "Sync") == "synced"


def test_a_collection_op_sees_the_requests_caller_on_its_own_thread(col, reset_settings, monkeypatch):
    # Anki runs CollectionOps on a worker thread, which does not inherit the
    # request's context; what the op publishes (review events) must still
    # know the app that sent it.
    from tsunagi.shared.permissions import current_caller

    class ThreadedOp:
        def __init__(self, *, parent, op):
            self._op, self._success = op, None

        def success(self, cb):
            self._success = cb

        def failure(self, cb):
            pass

        def run_in_background(self, *, initiator=None):
            box = {}
            worker = threading.Thread(target=lambda: box.update(res=self._op(col)))
            worker.start()
            worker.join()
            self._success(box["res"])

    monkeypatch.setattr(ops, "CollectionOp", ThreadedOp)
    reset_settings.update(apps=[{"name": "Phone", "key": "k" * 32, "role": "default"}])
    token = current_caller.set(reset_settings.resolve_caller("k" * 32, False))
    seen = {}
    try:
        ops.collection_op_run_async(lambda c: current_caller.get(),
                                    on_success=lambda v: seen.update(v=v), on_failure=seen.update)
    finally:
        current_caller.reset(token)
    assert seen["v"].name == "Phone"


def test_only_tsunagis_wrapper_is_unwrapped(col):
    # An Anki result can have a `value` of its own; it comes back whole.
    from anki.collection import OpChanges

    class Result:
        value = "a field of the result"
        changes = OpChanges()

    result = Result()
    assert ops.collection_op_call(lambda col: result) is result
    assert ops.collection_op_call(lambda col: ops.ValueWithChanges(5, OpChanges())) == 5
    assert ops.collection_op_call(lambda col: 7) == 7   # a bare value gets empty changes
