from __future__ import annotations

import threading
from functools import wraps
from typing import Any, Callable, Concatenate, Optional, ParamSpec, TypeVar, cast

from anki.collection import Collection
from aqt import mw
from aqt.operations import CollectionOp, QueryOp

from ..shared.errors import AnkiBusyError, CollectionUnavailableError
from .events import ApiOp

P = ParamSpec("P")
R = TypeVar("R")

# Default wait for cross-thread operations; overridden from config
# ("op_timeout_seconds") at server start.
OP_TIMEOUT: float = 15.0


class ValueWithChanges:
    """
    Return this from a collection-op adapter to carry a caller-facing value
    AND the backend's real OpChanges. CollectionOp hands `.changes` to
    operation_did_execute - which is what makes Anki's open windows (the
    browser especially) repaint after an API mutation, and what puts the true
    flags on the event stream - while `_success` unwraps `.value` for the
    caller. Without it the op reports a fabricated blank OpChanges: no
    repaint, no event.

    Wrapper protos (OpChangesWithCount/WithId/...) are unwrapped to the inner
    OpChanges here, because aqt passes `.changes` to the hook verbatim and
    col.op_made_changes() expects the bare message.
    """
    __slots__ = ("value", "changes")

    def __init__(self, value: Any, changes: Any) -> None:
        self.value = value
        self.changes = getattr(changes, "changes", changes)

def _wait(done: threading.Event, box: dict[str, Any], timeout: Optional[float], what: str) -> Any:
    if not done.wait(OP_TIMEOUT if timeout is None else timeout):
        raise AnkiBusyError(f"{what} timed out; Anki may be busy or blocked by a dialog")
    if "exc" in box:
        raise box["exc"]
    return box.get("result")

def call_on_main(fn: Callable[P, R], /, *args: P.args, timeout: Optional[float] = None, **kwargs: P.kwargs) -> R:
    """
    Run `fn(*args, **kwargs)` on Anki's UI thread and return its result.
    - If already on the UI thread, runs inline.
    - Raises AnkiBusyError if the UI thread doesn't respond within `timeout`
      (default: OP_TIMEOUT).
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
    return cast(R, _wait(done, box, timeout, "Main-thread call"))

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
    timeout: Optional[float] = None,
    **kwargs: P.kwargs,
) -> R:
    """
    Run 'fn(col, *args, **kwargs)' via QueryOp in a worker thread.
    Blocks caller until done (raises AnkiBusyError on timeout). No progress UI.
    """
    done = threading.Event()
    box: dict[str, Any] = {}

    def start_on_main() -> None:
        if mw.col is None:
            box.setdefault("exc", CollectionUnavailableError())
            done.set()
            return

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

    return cast(R, _wait(done, box, timeout, "Read operation"))

def query_op_run_async(
    fn: Callable[[Collection], R],
    *,
    on_success: Callable[[R], None],
    on_failure: Callable[[Exception], None],
) -> None:
    """
    Fire-and-forget QueryOp: start 'fn(col)' in a worker thread and return
    immediately. Exactly one of the callbacks fires when the op finishes; both
    run on the Qt main thread, so they must be quick and must not block.
    Used for work that can outlive OP_TIMEOUT (FSRS optimization) where the
    caller tracks completion itself (the job store) instead of waiting.
    """
    def start_on_main() -> None:
        if mw.col is None:
            on_failure(CollectionUnavailableError())
            return
        op = QueryOp(parent=mw, op=fn, success=on_success)
        try:
            op.failure(on_failure)  # type: ignore[attr-defined]
        except AttributeError:
            pass
        op.run_in_background()

    if threading.current_thread() is threading.main_thread():
        start_on_main()
    else:
        mw.taskman.run_on_main(start_on_main)


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
    timeout: Optional[float] = None,
    event_details: Optional[dict[str, Any]] = None,
    **kwargs: P.kwargs,
) -> R:
    """
    Run 'fn(col, *args, **kwargs)' via CollectionOp in a worker thread.
    `event_details` (note_ids etc.) rides on the op's initiator and surfaces
    on the event stream's matching `op` event.
    Blocks caller until done (raises AnkiBusyError on timeout). No progress UI.
    """
    done = threading.Event()
    box: dict[str, Any] = {}

    def start_on_main() -> None:
        if mw.col is None:
            box.setdefault("exc", CollectionUnavailableError())
            done.set()
            return

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
        # Tag the op so operation_did_execute subscribers (the event stream)
        # can attribute the change to the API rather than Anki's own UI, and
        # carry any identity the adapter attached (note_ids etc.).
        try:
            op.run_in_background(initiator=ApiOp(event_details))
        except TypeError:
            op.run_in_background()  # older signature without initiator

    if threading.current_thread() is threading.main_thread():
        start_on_main()
    else:
        mw.taskman.run_on_main(start_on_main)

    return cast(R, _wait(done, box, timeout, "Write operation"))


def as_collection_op(
    func: Optional[Callable[Concatenate[Collection, P], R]] = None,
    *,
    event_details: Optional[Callable[..., dict[str, Any]]] = None,
) -> Any:
    """
    Decorator: run function via CollectionOp (off UI thread), block for result.
    Bare (`@as_collection_op`) or parameterized: `event_details` is called
    with the wrapper's arguments (i.e. without `col`) and its dict rides on
    the op's event-stream record - how note ids get onto `op` events.
    """
    def decorate(f: Callable[Concatenate[Collection, P], R]) -> Callable[P, R]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            details = event_details(*args, **kwargs) if event_details else None
            return collection_op_call(f, *args, event_details=details, **kwargs)

        return wrapper  # type: ignore[return-value]

    if func is not None:
        return decorate(func)
    return decorate