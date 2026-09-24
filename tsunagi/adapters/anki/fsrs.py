"""
FSRS computations: parameter optimization, evaluation, and the simulator.

These live on the raw backend, not on Collection. Every supported Anki (26.08
and newer) has the same methods and arguments. `capabilities` still checks that
each method exists, so an Anki release that removes one reports that operation
as unsupported instead of failing inside a request.

compute_params/evaluate_params are plain (col, ...) functions on purpose: they
can outlive OP_TIMEOUT, so the router runs them through query_op_run_async and
tracks completion in the job store instead of blocking.
"""
from typing import Any, Dict, Optional

from anki.collection import Collection
from anki.scheduler_pb2 import SimulateFsrsReviewRequest

from ...shared.errors import UnsupportedAnkiVersionError
from ...shared.schemas.fsrs import (
    ComputeParamsRequest,
    EvaluateParamsRequest,
    SimulateRequest,
)
from ..ops import as_query_op, call_on_main

# Backend method behind each operation. evaluate_params_legacy is the one that
# evaluates the parameters the caller sends; evaluate_params takes none.
_OPERATIONS = {
    "compute_params": "compute_fsrs_params",
    "evaluate_params": "evaluate_params_legacy",
    "simulate": "simulate_fsrs_review",
    "simulate_workload": "simulate_fsrs_workload",
    "optimal_retention": "compute_optimal_retention",
}


def capabilities(backend: Any) -> Dict[str, Any]:
    """Report which operations this backend provides, without invoking them."""
    operations: Dict[str, Dict[str, Any]] = {
        name: {"available": callable(getattr(backend, method, None))}
        for name, method in _OPERATIONS.items()
    }
    for name in ("compute_params", "evaluate_params"):
        operations[name]["unsupported_options"] = []
    return {
        "supported": any(operation["available"] for operation in operations.values()),
        "operations": operations,
    }


def _require(be: Any, name: str) -> None:
    if not capabilities(be)["operations"][name]["available"]:
        raise UnsupportedAnkiVersionError(name.replace("_", "-"))


def check_supported(req: Any) -> None:
    """
    Pre-submit guard, safe from the request thread: only method checks on the
    backend, no collection reads. Lets the route answer 501 immediately
    instead of parking the refusal inside a background job.
    """
    from aqt import mw

    from ...shared.errors import CollectionUnavailableError

    if mw.col is None:
        raise CollectionUnavailableError()
    _require(mw.col._backend, "compute_params" if isinstance(req, ComputeParamsRequest) else "evaluate_params")


def compute_params(col: Collection, req: ComputeParamsRequest) -> Dict[str, Any]:
    """
    Optimize FSRS parameters from the review history matching `search`.
    Too little history returns empty params with fsrs_items 0.
    """
    be = col._backend
    _require(be, "compute_params")
    resp = be.compute_fsrs_params(
        search=req.search,
        current_params=req.current_params or [],
        ignore_revlogs_before_ms=req.ignore_revlogs_before_ms or 0,
        num_of_relearning_steps=req.num_of_relearning_steps or 0,
        health_check=bool(req.health_check),
    )
    return {
        "params": [float(p) for p in resp.params],
        "fsrs_items": int(resp.fsrs_items),
        "health_check_passed": bool(resp.health_check_passed) if req.health_check else None,
    }


def evaluate_params(col: Collection, req: EvaluateParamsRequest) -> Dict[str, float]:
    """Log loss / RMSE of the given parameters against the matching history."""
    be = col._backend
    _require(be, "evaluate_params")
    resp = be.evaluate_params_legacy(search=req.search, params=req.params,
                                     ignore_revlogs_before_ms=req.ignore_revlogs_before_ms or 0)
    return {"log_loss": float(resp.log_loss), "rmse_bins": float(resp.rmse_bins)}


def _simulate_proto(req: SimulateRequest) -> Any:
    return SimulateFsrsReviewRequest(
        params=req.params,
        desired_retention=req.desired_retention,
        deck_size=req.deck_size,
        days_to_simulate=req.days_to_simulate,
        new_limit=req.new_limit,
        review_limit=req.review_limit,
        max_interval=req.max_interval,
        search=req.search,
    )


@as_query_op
def simulate(col: Collection, req: SimulateRequest) -> Dict[str, Any]:
    _require(col._backend, "simulate")
    resp = col._backend.simulate_fsrs_review(_simulate_proto(req))
    return {
        "accumulated_knowledge_acquisition":
            [float(v) for v in resp.accumulated_knowledge_acquisition],
        "daily_review_count": [int(v) for v in resp.daily_review_count],
        "daily_new_count": [int(v) for v in resp.daily_new_count],
        "daily_time_cost": [float(v) for v in resp.daily_time_cost],
    }


@as_query_op
def simulate_workload(col: Collection, req: SimulateRequest) -> Dict[str, Any]:
    _require(col._backend, "simulate_workload")
    resp = col._backend.simulate_fsrs_workload(_simulate_proto(req))
    return {
        "cost": {int(k): float(v) for k, v in resp.cost.items()},
        "memorized": {int(k): float(v) for k, v in resp.memorized.items()},
        # A scalar, unlike its siblings: memorized count with no further reviews.
        "reviewless_end_memorized": float(resp.reviewless_end_memorized),
        "review_count": {int(k): float(v) for k, v in resp.review_count.items()},
    }


@as_query_op
def optimal_retention(col: Collection, req: SimulateRequest) -> float:
    _require(col._backend, "optimal_retention")
    return float(col._backend.compute_optimal_retention(_simulate_proto(req)))


def read_progress() -> Optional[Dict[str, int]]:
    """
    Best-effort {current, total} of the active computation, from Anki's global
    progress. Unknown shapes degrade to None, never raise.
    """
    from aqt import mw

    try:
        progress = call_on_main(lambda: mw.col.latest_progress(), timeout=2)
        active = progress.WhichOneof("value")
        if active in ("compute_params", "compute_retention"):
            sub = getattr(progress, active)
            return {"current": int(sub.current), "total": int(sub.total)}
    except Exception:
        pass
    return None


def request_abort() -> None:
    """Ask the backend to abort the active computation (global, like progress)."""
    from aqt import mw

    call_on_main(lambda: mw.col.set_wants_abort())
