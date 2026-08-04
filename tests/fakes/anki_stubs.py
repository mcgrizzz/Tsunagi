"""
Fake `aqt` module so tsunagi's Anki-facing code imports and runs under pytest.
Everything is synchronous and in-process: run_on_main calls inline,
QueryOp/CollectionOp execute immediately against `mw.col`.

`anki` itself is NOT faked - the real pylib is a test dependency and `mw.col`
is a real Collection. Only `aqt` is stubbed, because it drags in Qt and its
threading is the part we actually want to short-circuit. Anything from
anki.collection / anki.errors / anki.utils is the genuine article.

Faithful to the exact contract in tsunagi/adapters/ops.py:
- QueryOp(parent=, op=, success=) + .failure(cb) + .run_in_background();
  success receives the raw result.
- CollectionOp(parent=, op=) with .success(cb)/.failure(cb) attached AFTER
  construction; success receives the ResultWithChanges object raw (ops.py
  unwraps .value itself).

The `mw` object itself must stay the same instance forever because ops.py
does `from aqt import mw` once at import time; the `col` fixture swaps
`mw.col` underneath it.
"""
import sys
import types


class _TaskMan:
    def run_on_main(self, fn):
        fn()


class _FakeMainWindow:
    def __init__(self):
        self.col = None
        self.taskman = _TaskMan()
        # notesInfo reports the profile name
        self.pm = types.SimpleNamespace(name="User 1")


mw = _FakeMainWindow()


class QueryOp:
    def __init__(self, *, parent, op, success):
        self._op = op
        self._success = success
        self._failure = None

    def failure(self, cb):
        self._failure = cb

    def run_in_background(self):
        try:
            res = self._op(mw.col)
        except Exception as e:
            if self._failure is None:
                raise
            self._failure(e)
        else:
            self._success(res)


class CollectionOp:
    def __init__(self, *, parent, op):
        self._op = op
        self._success = None
        self._failure = None

    def success(self, cb):
        self._success = cb

    def failure(self, cb):
        self._failure = cb

    def run_in_background(self, *, initiator=None):
        self.initiator = initiator  # recorded so tests can assert tagging
        try:
            res = self._op(mw.col)
        except Exception as e:
            if self._failure is None:
                raise
            self._failure(e)
        else:
            if self._success is not None:
                self._success(res)


def install() -> None:
    """Register the fake aqt modules in sys.modules (idempotent)."""
    if "aqt" in sys.modules:
        return

    aqt_mod = types.ModuleType("aqt")
    aqt_mod.mw = mw
    aqt_ops_mod = types.ModuleType("aqt.operations")
    aqt_ops_mod.QueryOp = QueryOp
    aqt_ops_mod.CollectionOp = CollectionOp
    aqt_mod.operations = aqt_ops_mod

    sys.modules["aqt"] = aqt_mod
    sys.modules["aqt.operations"] = aqt_ops_mod
