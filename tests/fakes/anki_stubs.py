"""
Fake `aqt` / `anki` modules so tsunagi's Anki-facing code imports and runs
under pytest. Everything is synchronous and in-process: run_on_main calls
inline, QueryOp/CollectionOp execute immediately against `mw.col`.

Faithful to the exact contract in tsunagi/adapters/ops.py:
- QueryOp(parent=, op=, success=) + .failure(cb) + .run_in_background();
  success receives the raw result.
- CollectionOp(parent=, op=) with .success(cb)/.failure(cb) attached AFTER
  construction; success receives the ResultWithChanges object raw (ops.py
  unwraps .value itself). ops.py imports anki.collection.OpChanges inside
  the op wrapper, so it must be zero-arg constructible.

Tests assign a FakeCollection to `mw.col` (see the fake_col fixture) - the
`mw` object itself must stay the same instance forever because ops.py does
`from aqt import mw` once at import time.
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


mw = _FakeMainWindow()


class Collection:  # only used for type annotations in adapters/ops
    pass


class OpChanges:
    pass


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

    def run_in_background(self):
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
    """Register the fake modules in sys.modules (idempotent)."""
    if "aqt" in sys.modules:
        return

    anki_mod = types.ModuleType("anki")
    anki_col_mod = types.ModuleType("anki.collection")
    anki_col_mod.Collection = Collection
    anki_col_mod.OpChanges = OpChanges
    anki_mod.collection = anki_col_mod

    aqt_mod = types.ModuleType("aqt")
    aqt_mod.mw = mw
    aqt_ops_mod = types.ModuleType("aqt.operations")
    aqt_ops_mod.QueryOp = QueryOp
    aqt_ops_mod.CollectionOp = CollectionOp
    aqt_mod.operations = aqt_ops_mod

    sys.modules["anki"] = anki_mod
    sys.modules["anki.collection"] = anki_col_mod
    sys.modules["aqt"] = aqt_mod
    sys.modules["aqt.operations"] = aqt_ops_mod
