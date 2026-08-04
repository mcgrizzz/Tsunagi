"""
FSRS computations: parameter optimization, evaluation, and the simulator.

These live on the raw backend, not on Collection, and the API diverged across
our supported range - 23.10 spells the optimizer compute_fsrs_weights(search),
newer Anki spells it compute_fsrs_params(...) with more options, and the
simulator group doesn't exist on 23.10 at all. Every function here
feature-detects with hasattr and normalizes to the modern vocabulary
("params"), so routes and clients never see the split.

compute_params/evaluate_params are plain (col, ...) functions on purpose: they
can outlive OP_TIMEOUT, so the router runs them through query_op_run_async and
tracks completion in the job store instead of blocking.
"""
from typing import Any, Dict, Optional

from anki.collection import Collection

from ...shared.errors import UnsupportedAnkiVersionError
from ...shared.schemas.fsrs import (
    ComputeParamsRequest,
    EvaluateParamsRequest,
    SimulateRequest,
)
from ..ops import as_query_op, call_on_main

# ComputeParamsRequest options the 23.10 optimizer has no equivalent for.
_NEWER_COMPUTE_OPTIONS = (
    "current_params",
    "ignore_revlogs_before_ms",
    "num_of_relearning_steps",
    "health_check",
)


def _require(col: Collection, attr: str, feature: str) -> None:
    if not hasattr(col._backend, attr):
        raise UnsupportedAnkiVersionError(feature)


def _legacy_unsupported(be: Any, req: Any) -> None:
    """
    Raise when `req` uses options the 23.10 spelling of the API has no
    equivalent for. Silently computing with different settings than asked for
    would be worse than refusing.
    """
    if isinstance(req, ComputeParamsRequest) and not hasattr(be, "compute_fsrs_params"):
        sent = [name for name in _NEWER_COMPUTE_OPTIONS
                if getattr(req, name) is not None]
        if sent:
            raise UnsupportedAnkiVersionError(
                "compute-params option(s) " + ", ".join(sent))
    elif isinstance(req, EvaluateParamsRequest) and not hasattr(be, "evaluate_params_legacy"):
        if req.ignore_revlogs_before_ms is not None:
            raise UnsupportedAnkiVersionError(
                "evaluate-params option ignore_revlogs_before_ms")


def check_supported(req: Any) -> None:
    """
    Pre-submit guard, safe from the request thread: only hasattr checks on the
    backend, no collection access. Lets the route answer 501 immediately
    instead of parking the refusal inside a background job.
    """
    from aqt import mw

    from ...shared.errors import CollectionUnavailableError

    if mw.col is None:
        raise CollectionUnavailableError()
    _legacy_unsupported(mw.col._backend, req)


def compute_params(col: Collection, req: ComputeParamsRequest) -> Dict[str, Any]:
    """
    Optimize FSRS parameters from the review history matching `search`.

    Sparse-history behaviour differs by version and is surfaced as-is: 23.10
    raises InvalidInput ("Insufficient review history..."), newer Anki returns
    empty params with fsrs_items 0.
    """
    be = col._backend
    if hasattr(be, "compute_fsrs_params"):
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
            # The response bit is only meaningful when the check was asked for.
            "health_check_passed": bool(resp.health_check_passed)
            if req.health_check else None,
        }

    _legacy_unsupported(be, req)
    resp = be.compute_fsrs_weights(search=req.search)
    return {
        "params": [float(w) for w in resp.weights],
        "fsrs_items": int(resp.fsrs_items),
        "health_check_passed": None,
    }


def evaluate_params(col: Collection, req: EvaluateParamsRequest) -> Dict[str, float]:
    """Log loss / RMSE of the given parameters against the matching history."""
    be = col._backend
    if hasattr(be, "evaluate_params_legacy"):
        resp = be.evaluate_params_legacy(
            params=req.params,
            search=req.search,
            ignore_revlogs_before_ms=req.ignore_revlogs_before_ms or 0,
        )
    else:
        _legacy_unsupported(be, req)
        resp = be.evaluate_weights(weights=req.params, search=req.search)
    return {"log_loss": float(resp.log_loss), "rmse_bins": float(resp.rmse_bins)}


def _simulate_proto(req: SimulateRequest) -> Any:
    # Imported inside the gated functions: the message doesn't exist on 23.10.
    from anki.scheduler_pb2 import SimulateFsrsReviewRequest

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
    _require(col, "simulate_fsrs_review", "FSRS simulation")
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
    _require(col, "simulate_fsrs_workload", "FSRS simulation")
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
    _require(col, "compute_optimal_retention", "FSRS simulation")
    # 23.10 has a compute_optimal_retention too, but with an incompatible
    # signature - the simulate-request check above gates the whole group.
    _require(col, "simulate_fsrs_review", "FSRS simulation")
    return float(col._backend.compute_optimal_retention(_simulate_proto(req)))


def read_progress() -> Optional[Dict[str, int]]:
    """
    Best-effort {current, total} of the active computation, from Anki's global
    progress. The oneof was renamed across our range (compute_weights ->
    compute_params), so unknown shapes degrade to None, never raise.
    """
    from aqt import mw

    try:
        progress = call_on_main(lambda: mw.col.latest_progress(), timeout=2)
        active = progress.WhichOneof("value")
        if active in ("compute_params", "compute_weights", "compute_retention"):
            sub = getattr(progress, active)
            return {"current": int(sub.current), "total": int(sub.total)}
    except Exception:
        pass
    return None


def request_abort() -> None:
    """Ask the backend to abort the active computation (global, like progress)."""
    from aqt import mw

    call_on_main(lambda: mw.col.set_wants_abort())
