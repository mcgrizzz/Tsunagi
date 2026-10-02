"""
A blocking op call made on Anki's main thread (backlog 8.13). The op's result
arrives on that thread, so waiting there can only time out: it took the whole
op_timeout_seconds (forever with FOREVER) and then reported Anki as busy. It
now fails at once and says why.
"""
import time

import pytest
from fakes import anki_stubs

from tsunagi.adapters import ops


@pytest.fixture()
def deferred(monkeypatch):
    """Ops finish later, as in Anki: in the background, then back on the main thread."""
    queued = []
    for cls in (anki_stubs.QueryOp, anki_stubs.CollectionOp):
        real = cls.run_in_background
        monkeypatch.setattr(cls, "run_in_background",
                            lambda self, *a, _real=real, **k: queued.append(lambda: _real(self, *a, **k)))
    monkeypatch.setattr(ops, "OP_TIMEOUT", 5.0)
    return queued


@pytest.mark.parametrize("call", [
    lambda: ops.query_op_call(lambda col: col.note_count()),
    lambda: ops.collection_op_call(lambda col: col.set_config("tsunagi_probe", 1)),
], ids=["read", "write"])
def test_a_wait_on_the_main_thread_fails_at_once(col, deferred, call):
    start = time.perf_counter()
    with pytest.raises(RuntimeError, match="main thread"):
        call()
    assert time.perf_counter() - start < 1


def test_an_op_that_finishes_inline_still_returns(col):
    # Nothing to wait for: the result is already there.
    assert ops.query_op_call(lambda col: col.note_count()) == 0
