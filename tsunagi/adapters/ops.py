from __future__ import annotations

import threading
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar, Concatenate, cast

from aqt import mw
from aqt.operations import QueryOp, CollectionOp
from anki.collection import Collection

P = ParamSpec("P")
R = TypeVar("R")

def call_on_main(fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
    """
    Run `fn(*args, **kwargs)` on Anki's UI thread and return its result.
    - If already on the UI thread, runs inline.
    - Waits indefinitely (no timeout).
    - Propagates the original exception from the UI thread.
    """
    if threading.current_thread() is threading.main_thread():
        return fn(*args, **kwargs)

    done = threading.Event()
    box: dict[str, Any] = {"result": None}

    def _call() -> None:
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as e:
            box["exc"] = e
        finally:
            done.set()

    mw.taskman.run_on_main(_call)
    done.wait()  # wait indefinitely

    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return box["result"]  # type: ignore[no-any-return]

def on_main(func: Callable[P, R]) -> Callable[P, R]:
    """
    Decorator: ensure the wrapped function executes on Anki's UI thread.
    Usage:
        @on_main
        def list_models() -> list[ModelInfo]:
            ...
    """
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return call_on_main(func, *args, **kwargs)
    return wrapper  # type: ignore[return-value]


def query_op_call(
    fn: Callable[Concatenate[Collection, P], R],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """
    Run 'fn(col, *args, **kwargs)' via QueryOp in a worker thread.
    Blocks caller until done. No progress UI.
    """
    done = threading.Event()
    box: dict[str, Any] = {}

    def start_on_main() -> None:
        def _success(res: Any) -> None:
            box.setdefault("result", res)
            done.set()

        def _failure(exc: Exception) -> None:
            box.setdefault("exc", exc)
            done.set()

        op = QueryOp(
            parent=mw,
            op=lambda col: fn(col, *args, **kwargs),
            success=_success,
        )
        # Some builds expose .failure(); if not, ignore.
        try:
            op.failure(_failure)  # type: ignore[attr-defined]
        except AttributeError:
            pass
        op.run_in_background()

    if threading.current_thread() is threading.main_thread():
        start_on_main()
    else:
        mw.taskman.run_on_main(start_on_main)

    done.wait()  # block indefinitely
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return cast(R, box.get("result"))

def as_query_op(
    func: Callable[Concatenate[Collection, P], R],
) -> Callable[P, R]:
    """Decorator: run function via QueryOp (off UI thread), block for result."""
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return query_op_call(func, *args, **kwargs)

    return wrapper  # type: ignore[return-value]

def collection_op_call(
    fn: Callable[Concatenate[Collection, P], R],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """
    Run 'fn(col, *args, **kwargs)' via CollectionOp in a worker thread.
    Blocks caller until done. No progress UI.
    """
    done = threading.Event()
    box: dict[str, Any] = {}

    def start_on_main() -> None:
        def _success(res: Any) -> None:
            # Extract the actual value from ResultWithChanges if present
            if hasattr(res, 'value'):
                box.setdefault("result", res.value)
            else:
                box.setdefault("result", res)
            done.set()

        def _failure(exc: Exception) -> None:
            box.setdefault("exc", exc)
            done.set()

        # Wrap the function to return a ResultWithChanges object
        def wrapped_op(col: Collection) -> Any:
            result = fn(col, *args, **kwargs)
            # If the result already has .changes, return as-is
            if hasattr(result, 'changes'):
                return result
            # Otherwise, wrap it with empty changes
            from anki.collection import OpChanges
            class ResultWithChanges:
                def __init__(self, value, changes):
                    self.value = value
                    self.changes = changes
            return ResultWithChanges(result, OpChanges())

        # Cast to appease type checkers: (Collection) -> ResultWithChanges[Any]
        op = CollectionOp(
            parent=mw,
            op=cast(
                Callable[[Collection], Any],
                wrapped_op,
            ),  # type: ignore[arg-type]
        )
        try:
            op.success(_success)  # type: ignore[attr-defined]
        except AttributeError:
            pass
        try:
            op.failure(_failure)  # type: ignore[attr-defined]
        except AttributeError:
            pass
        op.run_in_background()

    if threading.current_thread() is threading.main_thread():
        start_on_main()
    else:
        mw.taskman.run_on_main(start_on_main)

    done.wait()
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return cast(R, box.get("result"))


def as_collection_op(
    func: Callable[Concatenate[Collection, P], R],
) -> Callable[P, R]:
    """Decorator: run function via CollectionOp (off UI thread), block for result."""
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return collection_op_call(func, *args, **kwargs)

    return wrapper  # type: ignore[return-value]