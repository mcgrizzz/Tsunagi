"""Temporary live routing measurements, installed from Anki's debug console.

Execute this file with runpy.run_path(). Call stop_routing_profile() in the
returned namespace to restore the original functions. No collection writes.
Metrics go to routing_profile.jsonl beside this script; no card content is logged.
Restarting Anki also removes the instrumentation. Use on a disposable profile.
"""

import contextvars
import functools
import json
import sys
import threading
import time
from pathlib import Path

_output = Path(__file__).with_name("routing_profile.jsonl")
_current = contextvars.ContextVar("routing_profile", default=None)
_patches = []
_lock = threading.Lock()


def _module(suffix):
    matches = [m for name, m in sys.modules.items() if name.endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one loaded {suffix} module, found {len(matches)}")
    return matches[0]


_routes = _module(".shared.route_factory")
_ops = _module(".adapters.ops")
_cards = _module(".adapters.anki.cards")
if getattr(_routes._execute_query, "_routing_profile", False):
    raise RuntimeError("Routing profiler is already installed")


def _patch(module, name, replacement):
    _patches.append((module, name, getattr(module, name)))
    setattr(module, name, replacement)


def _record(profile, name, elapsed, count=1):
    with _lock:
        metric = profile["phases"].setdefault(name, {"calls": 0, "ms": 0.0})
        metric["calls"] += count
        metric["ms"] += elapsed * 1000


def _timed(module, name):
    original = getattr(module, name)

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        profile = _current.get()
        if profile is None:
            return original(*args, **kwargs)
        start = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            _record(profile, name, time.perf_counter() - start)

    _patch(module, name, wrapped)


_query_op = _ops.query_op_call


@functools.wraps(_query_op)
def _profile_op(fn, *args, **kwargs):
    profile = _current.get()
    if profile is None:
        return _query_op(fn, *args, **kwargs)
    start = time.perf_counter()
    span = {"name": fn.__name__}

    @functools.wraps(fn)
    def worker(col, *worker_args, **worker_kwargs):
        token = _current.set(profile)
        entered = time.perf_counter()
        span["before_worker_ms"] = (entered - start) * 1000
        try:
            result = fn(col, *worker_args, **worker_kwargs)
            if isinstance(result, (list, tuple)):
                span["rows"] = len(result)
            return result
        finally:
            span["worker_ms"] = (time.perf_counter() - entered) * 1000
            span["finished"] = time.perf_counter()
            _current.reset(token)

    try:
        return _query_op(worker, *args, **kwargs)
    finally:
        end = time.perf_counter()
        span["total_ms"] = (end - start) * 1000
        finished = span.pop("finished", None)
        if finished is not None:
            span["after_worker_ms"] = (end - finished) * 1000
        profile["operations"].append(span)


_execute = _routes._execute_query
_build_predicate = _routes.build_predicate


@functools.wraps(_build_predicate)
def _profile_predicate(*args, **kwargs):
    predicate = _build_predicate(*args, **kwargs)

    @functools.wraps(predicate)
    def evaluate(row):
        profile = _current.get()
        if profile is None:
            return predicate(row)
        start = time.perf_counter()
        try:
            return predicate(row)
        finally:
            _record(profile, "predicate", time.perf_counter() - start)

    return evaluate


@functools.wraps(_execute)
def _profile_execute(*args, **kwargs):
    profile = {"phases": {}, "operations": []}
    token = _current.set(profile)
    start = time.perf_counter()
    try:
        result = _execute(*args, **kwargs)
        profile["returned_rows"] = len(result.items)
        return result
    finally:
        profile["elapsed_ms"] = (time.perf_counter() - start) * 1000
        _current.reset(token)
        with _lock, _output.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(profile) + "\n")


def stop_routing_profile():
    """Restore functions after all measured requests have finished."""
    for module, name, original in reversed(_patches):
        setattr(module, name, original)
    _patches.clear()
    print(f"Routing profiling stopped. Measurements: {_output}")


_profile_execute._routing_profile = True
_patch(_ops, "query_op_call", _profile_op)
_patch(_routes, "build_predicate", _profile_predicate)
for _name in ("_card_info", "_deck_names", "_next_reviews", "_retrievability"):
    _timed(_cards, _name)
for _name in ("make_plan", "_as_dict", "_finish"):
    _timed(_routes, _name)
_patch(_routes, "_execute_query", _profile_execute)
print(f"Routing profiling installed. Measurements: {_output}")
