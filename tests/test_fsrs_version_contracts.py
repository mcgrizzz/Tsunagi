"""The FSRS adapter forwards request options to Anki's backend unchanged."""
from types import SimpleNamespace

from tsunagi.adapters.anki.fsrs import compute_params, evaluate_params
from tsunagi.shared.schemas.fsrs import ComputeParamsRequest, EvaluateParamsRequest


def backend():
    calls = []

    def compute_fsrs_params(**kwargs):
        calls.append(("compute", kwargs))
        return SimpleNamespace(params=[1.5], fsrs_items=3, health_check_passed=True)

    def evaluate_params_legacy(**kwargs):
        calls.append(("evaluate", kwargs))
        return SimpleNamespace(log_loss=0.25, rmse_bins=0.5)

    be = SimpleNamespace(compute_fsrs_params=compute_fsrs_params,
                         evaluate_params_legacy=evaluate_params_legacy)
    return SimpleNamespace(_backend=be), calls


def test_optimizer_forwards_every_option():
    col, calls = backend()
    result = compute_params(col, ComputeParamsRequest(
        search="deck:JP", current_params=[0.5], ignore_revlogs_before_ms=10,
        num_of_relearning_steps=2, health_check=True))
    assert calls == [("compute", {"search": "deck:JP", "current_params": [0.5],
                                  "ignore_revlogs_before_ms": 10, "num_of_relearning_steps": 2,
                                  "health_check": True})]
    assert result == {"params": [1.5], "fsrs_items": 3, "health_check_passed": True}


def test_optimizer_defaults_omitted_options():
    col, calls = backend()
    result = compute_params(col, ComputeParamsRequest(search=""))
    assert calls[0][1] == {"search": "", "current_params": [], "ignore_revlogs_before_ms": 0,
                           "num_of_relearning_steps": 0, "health_check": False}
    assert result["health_check_passed"] is None


def test_evaluator_forwards_params_and_cutoff():
    col, calls = backend()
    result = evaluate_params(col, EvaluateParamsRequest(search="x", params=[0.1, 0.2],
                                                        ignore_revlogs_before_ms=5))
    assert calls == [("evaluate", {"search": "x", "params": [0.1, 0.2], "ignore_revlogs_before_ms": 5})]
    assert result == {"log_loss": 0.25, "rmse_bins": 0.5}
