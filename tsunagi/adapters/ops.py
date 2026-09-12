from __future__ import annotations

import logging
import threading
from concurrent.futures import Future
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, cast

from anki.collection import Collection
from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from typing_extensions import Concatenate, ParamSpec

from ..shared.errors import AnkiBusyError, CollectionUnavailableError
from .event_results import freeze_changes
from .events import ApiOp, broker

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

    event_changes is an optional factory of resource fetch/remove IDs.
    Declare only fully covered resources and use existing operation results;
    the runner copies them before success callbacks, only for data listeners.
    """
    __slots__ = ("value", "changes", "event_changes")

    def __init__(self, value: Any, changes: Any, *,
                 event_changes: Optional[Callable[[], dict]] = None) -> None:
        self.value = value
        self.event_changes = event_changes
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

def call_on_main_interactive(fn: Callable[[], R]) -> R:
    """Bound UI dispatch, then wait for user interaction without a deadline.

    A request that expires before dispatch is cancelled, so its queued callback
    cannot open a dialog after the caller has received a timeout.
    """
    if threading.current_thread() is threading.main_thread():
        return fn()

    started = threading.Event()
    result: Future[R] = Future()

    def run() -> None:
        if not result.set_running_or_notify_cancel():
            return
        started.set()
        try:
            result.set_result(fn())
        except BaseException as exc:
            result.set_exception(exc)

    mw.taskman.run_on_main(run)
    if not started.wait(OP_TIMEOUT) and result.cancel():
        raise AnkiBusyError("Main-thread dispatch timed out; Anki did not accept the dialog request")
    # If dispatch won the race with the timeout, it now owns the request.
    return result.result()


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

def collection_op_run_async(
    fn: Callable[Concatenate[Collection, P], R],
    /,
    *args: P.args,
    on_success: Callable[[Any], None],
    on_failure: Callable[[Exception], None],
    event_details: Optional[dict[str, Any]] = None,
    **kwargs: P.kwargs,
) -> None:
    """Run a write through Anki's CollectionOp, reporting completion via callbacks."""
    # Capture identity only; collection methods still run on Anki's op thread.
    collection = mw.col

    def start_on_main() -> None:
        if collection is None or mw.col is not collection:
            on_failure(CollectionUnavailableError())
            return

        def _success(res: Any) -> None:
            # Extract the actual value from ResultWithChanges if present
            on_success(res.value if hasattr(res, 'value') else res)

        def _failure(exc: Exception) -> None:
            on_failure(exc)

        initiator = ApiOp(event_details, collection=collection)

        # Wrap the function to return a ResultWithChanges object
        def wrapped_op(col: Collection) -> Any:
            if col is not collection:
                raise CollectionUnavailableError()
            result = fn(col, *args, **kwargs)
            if isinstance(result, ValueWithChanges) and result.event_changes:
                # Capture on the collection thread, before Anki's success hook.
                # Event decoration must never turn a successful write into a failure.
                try:
                    if broker.has_change_subscribers():
                        initiator.changes = freeze_changes(result.event_changes())
                except Exception:
                    initiator.changes = {}
                    logging.getLogger(__name__).exception(
                        "Could not prepare changed IDs; using resource invalidation")
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
            op.run_in_background(initiator=initiator)
        except TypeError:
            op.run_in_background()  # older signature without initiator

    def dispatch() -> None:
        try:
            start_on_main()
        except Exception as exc:
            on_failure(exc)

    if threading.current_thread() is threading.main_thread():
        dispatch()
    else:
        try:
            mw.taskman.run_on_main(dispatch)
        except Exception as exc:
            on_failure(exc)


def collection_op_call(
    fn: Callable[Concatenate[Collection, P], R],
    /,
    *args: P.args,
    timeout: Optional[float] = None,
    event_details: Optional[dict[str, Any]] = None,
    **kwargs: P.kwargs,
) -> R:
    """Wait for a CollectionOp result, retaining the ordinary operation deadline."""
    done = threading.Event()
    box: dict[str, Any] = {}

    def success(result: Any) -> None:
        box["result"] = result
        done.set()

    def failure(exc: Exception) -> None:
        box["exc"] = exc
        done.set()

    collection_op_run_async(fn, *args, on_success=success, on_failure=failure,
                            event_details=event_details, **kwargs)
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
    the op's event-stream record - how note ids get onto `change` events.
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
