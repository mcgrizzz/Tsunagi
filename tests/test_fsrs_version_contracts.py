"""Intermediate Anki signatures must work even when CI runs a newer wheel."""

from types import SimpleNamespace

import pytest

from tsunagi.adapters.anki.fsrs import capabilities, compute_params, evaluate_params
from tsunagi.shared.errors import UnsupportedAnkiVersionError
from tsunagi.shared.schemas.fsrs import ComputeParamsRequest, EvaluateParamsRequest


class Weights2310:
    def compute_fsrs_weights(self, search):
        self.received = {"search": search}
        return SimpleNamespace(weights=[1.0], fsrs_items=10)

    def evaluate_weights(self, *, weights, search):
        self.received = {"params": weights, "search": search}
        return SimpleNamespace(log_loss=0.2, rmse_bins=0.1)


class Weights2406:
    def compute_fsrs_weights(self, *, search, current_weights, ignore_revlogs_before_ms):
        self.received = {"search": search, "params": current_weights, "cutoff": ignore_revlogs_before_ms}
        return SimpleNamespace(weights=current_weights, fsrs_items=10)

    def evaluate_weights(self, *, weights, search, ignore_revlogs_before_ms):
        self.received = {"search": search, "params": weights, "cutoff": ignore_revlogs_before_ms}
        return SimpleNamespace(log_loss=0.2, rmse_bins=0.1)


class Params2411:
    def compute_fsrs_params(self, *, search, current_params, ignore_revlogs_before_ms):
        self.received = {"search": search, "params": current_params, "cutoff": ignore_revlogs_before_ms}
        return SimpleNamespace(params=current_params, fsrs_items=10)

    def evaluate_params(self, *, params, search, ignore_revlogs_before_ms):
        self.received = {"search": search, "params": params, "cutoff": ignore_revlogs_before_ms}
        return SimpleNamespace(log_loss=0.2, rmse_bins=0.1)


class Params2502(Params2411):
    def compute_fsrs_params(self, *, search, current_params, ignore_revlogs_before_ms,
                            num_of_relearning_steps):
        self.steps = num_of_relearning_steps
        return super().compute_fsrs_params(search=search, current_params=current_params,
                                          ignore_revlogs_before_ms=ignore_revlogs_before_ms)


@pytest.mark.parametrize("backend_type", [Weights2406, Params2411, Params2502])
def test_intermediate_optimizer_forwards_supported_options(backend_type):
    backend = backend_type()
    result = compute_params(SimpleNamespace(_backend=backend), ComputeParamsRequest(
        search="deck:Default", current_params=[1.25], ignore_revlogs_before_ms=123))
    assert backend.received == {"search": "deck:Default", "params": [1.25], "cutoff": 123}
    assert result == {"params": [1.25], "fsrs_items": 10, "health_check_passed": None}
    assert capabilities(backend)["operations"]["evaluate_params"]["available"]


@pytest.mark.parametrize("backend_type", [Weights2406, Params2411, Params2502])
def test_intermediate_evaluator_forwards_cutoff(backend_type):
    backend = backend_type()
    result = evaluate_params(SimpleNamespace(_backend=backend), EvaluateParamsRequest(
        search="deck:Default", params=[1.25], ignore_revlogs_before_ms=123))
    assert backend.received == {"search": "deck:Default", "params": [1.25], "cutoff": 123}
    assert result == {"log_loss": 0.2, "rmse_bins": 0.1}


@pytest.mark.parametrize("backend_type,unsupported", [
    (Weights2310, {"current_params", "ignore_revlogs_before_ms", "num_of_relearning_steps", "health_check"}),
    (Weights2406, {"num_of_relearning_steps", "health_check"}),
    (Params2411, {"num_of_relearning_steps", "health_check"}),
    (Params2502, {"health_check"}),
])
def test_discovery_and_rejection_agree_for_explicit_options(backend_type, unsupported):
    backend = backend_type()
    support = capabilities(backend)["operations"]["compute_params"]
    assert set(support["unsupported_options"]) == unsupported
    defaults = {"current_params": [], "ignore_revlogs_before_ms": 0,
                "num_of_relearning_steps": 0, "health_check": False}
    for option in unsupported:
        with pytest.raises(UnsupportedAnkiVersionError, match=option):
            compute_params(SimpleNamespace(_backend=backend), ComputeParamsRequest(**{option: defaults[option]}))
    assert not hasattr(backend, "received")


def test_2310_keeps_search_only_optimizer():
    backend = Weights2310()
    result = compute_params(SimpleNamespace(_backend=backend), ComputeParamsRequest(search="tag:test"))
    assert backend.received == {"search": "tag:test"}
    assert result["params"] == [1.0]


def test_relearning_steps_are_forwarded_when_supported():
    backend = Params2502()
    compute_params(SimpleNamespace(_backend=backend), ComputeParamsRequest(num_of_relearning_steps=3))
    assert backend.steps == 3
