"""
FSRS computations: parameter optimization, evaluation, and the simulator.

These live on the raw backend, not on Collection, and the API diverged across
our supported range - 23.10 spells the optimizer compute_fsrs_weights(search),
newer Anki spells it compute_fsrs_params(...) with more options, and the
simulator group doesn't exist on 23.10 at all. Every function here
checks method signatures/protobuf fields and normalizes to the modern vocabulary
("params"), so routes and clients never see the split.

compute_params/evaluate_params are plain (col, ...) functions on purpose: they
can outlive OP_TIMEOUT, so the router runs them through query_op_run_async and
tracks completion in the job store instead of blocking.
"""
from inspect import signature
from typing import Any, Dict, Optional

from anki.collection import Collection

from ...shared.errors import UnsupportedAnkiVersionError
from ...shared.schemas.fsrs import (
    ComputeParamsRequest,
    EvaluateParamsRequest,
    SimulateRequest,
)
from ..ops import as_query_op, call_on_main

# Native option names stay stable as Anki renames/adds backend arguments.
_COMPUTE_OPTIONS = {
    "current_params": "current_weights",
    "ignore_revlogs_before_ms": "ignore_revlogs_before_ms",
    "num_of_relearning_steps": "num_of_relearning_steps",
    "health_check": "health_check",
}


def _method(backend, *names):
    for name in names:
        method = getattr(backend, name, None)
        if callable(method):
            return method
    return None


def _option_names(method, aliases):
    parameters = signature(method).parameters if method is not None else {}
    return {name: name if name in parameters else alias
            for name, alias in aliases.items()
            if name in parameters or alias in parameters}


def _compute_method(backend):
    return _method(backend, "compute_fsrs_params", "compute_fsrs_weights")


def _evaluate_method(backend):
    return _method(backend, "evaluate_params_legacy", "evaluate_params", "evaluate_weights")


def capabilities(backend: Any) -> Dict[str, Any]:
    """Inspect the callable contracts without invoking backend methods."""
    compute = _compute_method(backend)
    evaluate = _evaluate_method(backend)
    simulation = callable(getattr(backend, "simulate_fsrs_review", None))
    retention = _method(backend, "compute_optimal_retention")
    compute_options = _option_names(compute, _COMPUTE_OPTIONS)
    evaluate_options = _option_names(evaluate, {"ignore_revlogs_before_ms": "ignore_revlogs_before_ms"})
    operations = {
        "compute_params": {
            "available": compute is not None,
            "unsupported_options": [name for name in _COMPUTE_OPTIONS
                                    if name not in compute_options],
        },
        "evaluate_params": {
            "available": evaluate is not None,
            "unsupported_options": [] if evaluate_options else ["ignore_revlogs_before_ms"],
        },
        "simulate": {"available": simulation},
        "simulate_workload": {"available": callable(getattr(backend, "simulate_fsrs_workload", None))},
        "optimal_retention": {
            # Earlier methods require loss_aversion and cannot honor this
            # endpoint's simulator request. Do not silently change its meaning.
            "available": simulation and retention is not None and "message" in signature(retention).parameters,
        },
    }
    return {
        "supported": any(operation["available"] for operation in operations.values()),
        "operations": operations,
    }


def _require(col: Collection, attr: str, feature: str) -> None:
    if not hasattr(col._backend, attr):
        raise UnsupportedAnkiVersionError(feature)


def _legacy_unsupported(be: Any, req: Any) -> None:
    """Reject explicitly supplied options this backend cannot honor."""
    name = "compute_params" if isinstance(req, ComputeParamsRequest) else "evaluate_params"
    operation = capabilities(be)["operations"][name]
    if not operation["available"]:
        raise UnsupportedAnkiVersionError(name.replace("_", "-"))
    sent = [option for option in operation["unsupported_options"]
            if getattr(req, option) is not None]
    if sent:
        raise UnsupportedAnkiVersionError(name.replace("_", "-") + " option(s) " + ", ".join(sent))


def check_supported(req: Any) -> None:
    """
    Pre-submit guard, safe from the request thread: only signature checks on the
    backend, no collection reads. Lets the route answer 501 immediately
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
    _legacy_unsupported(be, req)
    method = _compute_method(be)
    defaults = {"current_params": [], "ignore_revlogs_before_ms": 0,
                "num_of_relearning_steps": 0, "health_check": False}
    options = _option_names(method, _COMPUTE_OPTIONS)
    kwargs = {argument: getattr(req, name) if getattr(req, name) is not None else defaults[name]
              for name, argument in options.items()}
    resp = method(search=req.search, **kwargs)
    params = resp.params if hasattr(resp, "params") else resp.weights
    return {
        "params": [float(p) for p in params],
        "fsrs_items": int(resp.fsrs_items),
        "health_check_passed": bool(resp.health_check_passed) if req.health_check else None,
    }


def evaluate_params(col: Collection, req: EvaluateParamsRequest) -> Dict[str, float]:
    """Log loss / RMSE of the given parameters against the matching history."""
    be = col._backend
    _legacy_unsupported(be, req)
    method = _evaluate_method(be)
    options = _option_names(method, {"params": "weights",
                                    "ignore_revlogs_before_ms": "ignore_revlogs_before_ms"})
    values = {"params": req.params, "ignore_revlogs_before_ms": req.ignore_revlogs_before_ms or 0}
    resp = method(search=req.search, **{argument: values[name] for name, argument in options.items()})
    return {"log_loss": float(resp.log_loss), "rmse_bins": float(resp.rmse_bins)}


def _simulate_proto(req: SimulateRequest) -> Any:
    # Imported inside the gated functions: the message doesn't exist on 23.10.
    from anki.scheduler_pb2 import SimulateFsrsReviewRequest

    params_field = "params" if "params" in SimulateFsrsReviewRequest.DESCRIPTOR.fields_by_name else "weights"
    return SimulateFsrsReviewRequest(
        **{params_field: req.params},
        desired_retention=req.desired_retention,
        deck_size=req.deck_size,
        days_to_simulate=req.days_to_simulate,
        new_limit=req.new_limit,
        review_limit=req.review_limit,
        max_interval=req.max_interval,
        search=req.search,
    )


def _simulate_call(method, req):
    message = _simulate_proto(req)
    parameters = signature(method).parameters
    if "message" in parameters:
        return method(message)
    # Generated keyword wrappers require even the fields we leave at protobuf
    # defaults, e.g. 25.02's new_cards_ignore_review_limit=False.
    return method(**{name: getattr(message, name) for name in parameters})


@as_query_op
def simulate(col: Collection, req: SimulateRequest) -> Dict[str, Any]:
    _require(col, "simulate_fsrs_review", "FSRS simulation")
    resp = _simulate_call(col._backend.simulate_fsrs_review, req)
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
    if not capabilities(col._backend)["operations"]["optimal_retention"]["available"]:
        raise UnsupportedAnkiVersionError("FSRS optimal retention with simulator options")
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
