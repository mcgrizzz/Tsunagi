"""
Full-app tests for the FSRS surface: compute/evaluate jobs and the simulator.

The fake QueryOp (tests/fakes/anki_stubs.py) runs synchronously, so a job is
already terminal when the submit call returns - these tests assert final
states. The `running` status, live progress, and abort-mid-flight are Qt
main-thread behaviour, covered by the manual smoke checklist instead.

Version splits are asserted in both directions via hasattr on the backend:
the optimizer/evaluator changed spelling after 23.10, and the simulator group
doesn't exist there at all.
"""
from inspect import signature

import pytest
from anki._backend import RustBackend

from tsunagi.adapters.jobs import jobs

COMPUTE = getattr(RustBackend, "compute_fsrs_params", getattr(RustBackend, "compute_fsrs_weights", None))
EVALUATE = getattr(RustBackend, "evaluate_params_legacy",
                   getattr(RustBackend, "evaluate_params", getattr(RustBackend, "evaluate_weights", None)))
RETURNS_EMPTY_PARAMS = bool({"current_params", "current_weights"} & signature(COMPUTE).parameters.keys())
HAS_HEALTH_CHECK = "health_check" in signature(COMPUTE).parameters
HAS_EVALUATE_CUTOFF = "ignore_revlogs_before_ms" in signature(EVALUATE).parameters
HAS_WORKLOAD = hasattr(RustBackend, "simulate_fsrs_workload")
HAS_RETENTION = "message" in signature(RustBackend.compute_optimal_retention).parameters
HAS_SIMULATOR = hasattr(RustBackend, "simulate_fsrs_review")


@pytest.fixture(autouse=True)
def clean_jobs():
    jobs.reset()
    yield
    jobs.reset()


def submit_compute(client, body=None):
    return client.post("/v1/fsrs:compute-params", json=body or {})


def poll(client, job_id):
    return client.get(f"/v1/jobs/{job_id}")


class TestComputeParamsJob:
    def test_submit_returns_202_with_a_pollable_job(self, client):
        resp = submit_compute(client)
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        body = poll(client, job_id).json()
        assert body["id"] == job_id
        assert body["kind"] == "compute_params"
        # Synchronous fakes: the job is terminal by the time submit returns.
        assert body["status"] in ("done", "failed")

    @pytest.mark.skipif(RETURNS_EMPTY_PARAMS, reason="23.10 optimizer only")
    def test_sparse_history_fails_the_job_with_ankis_message(self, client):
        job_id = submit_compute(client).json()["job_id"]
        body = poll(client, job_id).json()
        assert body["status"] == "failed"
        assert "Insufficient review history" in body["error"]
        assert body["result"] is None

    @pytest.mark.skipif(not RETURNS_EMPTY_PARAMS, reason="newer optimizer only")
    def test_sparse_history_reports_done_with_empty_params(self, client):
        # Deliberately NOT normalized to match 23.10's error - this is what
        # this Anki version actually did.
        job_id = submit_compute(client).json()["job_id"]
        body = poll(client, job_id).json()
        assert body["status"] == "done"
        assert body["result"] == {
            "params": [], "fsrs_items": 0, "health_check_passed": None}

    @pytest.mark.skipif(HAS_HEALTH_CHECK, reason="health check is supported")
    def test_newer_options_are_501_before_submission(self, client):
        resp = submit_compute(client, {"health_check": True})
        assert resp.status_code == 501
        assert "Anki version" in resp.json()["detail"]
        # The refusal happened up front: no job was parked in the store.
        assert submit_compute(client).status_code == 202

    @pytest.mark.skipif(not HAS_HEALTH_CHECK, reason="health check is unsupported")
    def test_newer_options_accepted_on_newer_anki(self, client):
        resp = submit_compute(client, {"health_check": True,
                                       "num_of_relearning_steps": 1})
        assert resp.status_code == 202
        body = poll(client, resp.json()["job_id"]).json()
        assert body["status"] == "done"
        # health_check was asked for, so the response bit is surfaced.
        assert body["result"]["health_check_passed"] in (True, False)


class TestEvaluateParamsJob:
    def test_sparse_history_fails_with_ankis_message(self, client):
        # Both pinned versions refuse to score parameters with no history.
        resp = client.post("/v1/fsrs:evaluate-params", json={"params": []})
        assert resp.status_code == 202
        body = poll(client, resp.json()["job_id"]).json()
        assert body["kind"] == "evaluate_params"
        assert body["status"] == "failed"
        assert "Insufficient review history" in body["error"]

    @pytest.mark.skipif(HAS_EVALUATE_CUTOFF, reason="cutoff is supported")
    def test_newer_option_is_501_on_2310(self, client):
        resp = client.post("/v1/fsrs:evaluate-params", json={
            "params": [], "ignore_revlogs_before_ms": 1})
        assert resp.status_code == 501


class TestJobRoutes:
    def test_unknown_job_is_404(self, client):
        assert poll(client, "nope").status_code == 404
        assert client.post("/v1/jobs/nope:abort").status_code == 404

    def test_second_submit_while_active_is_409(self, client):
        active = jobs.create("compute_params")  # occupy the single slot
        resp = submit_compute(client)
        assert resp.status_code == 409
        assert active.id in resp.json()["detail"]

    def test_abort_of_an_active_job_is_acknowledged(self, client):
        active = jobs.create("compute_params")
        resp = client.post(f"/v1/jobs/{active.id}:abort")
        # The route only raises the backend's abort flag; the status flips to
        # `aborted` when the computation acknowledges (manual-smoke territory).
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_abort_of_a_finished_job_is_409(self, client):
        job_id = submit_compute(client).json()["job_id"]  # terminal already
        resp = client.post(f"/v1/jobs/{job_id}:abort")
        assert resp.status_code == 409
        assert "already" in resp.json()["detail"]

    def test_abort_that_beats_the_backend_wins(self, client, monkeypatch):
        # Anki's rust ThrottlingProgressHandler clears the global want_abort
        # flag when a computation starts, so an abort raised between submit
        # and backend entry would be silently erased. The op wrapper must
        # honor the recorded intent itself. Reproduce the race by landing the
        # abort after the job exists but before the op runs.
        from tsunagi.http.v1 import fsrs as fsrs_router
        real = fsrs_router.query_op_run_async

        def abort_then_run(fn, *, on_success, on_failure):
            active = next(iter(jobs._jobs.values()))
            jobs.mark_abort_requested(active.id)
            real(fn, on_success=on_success, on_failure=on_failure)

        monkeypatch.setattr(fsrs_router, "query_op_run_async", abort_then_run)
        job_id = submit_compute(client).json()["job_id"]
        body = poll(client, job_id).json()
        assert body["status"] == "aborted"
        assert "before the computation started" in body["error"]
        assert body["result"] is None

    def test_abort_during_backend_work_discards_the_result(self, client, monkeypatch):
        # The other side of the same guarantee: Anki's revlog-load phase never
        # checks the abort flag and training clears it, so the backend can
        # finish despite an acknowledged abort. The contract is that a 200
        # from :abort means the job ends aborted - so a result that arrives
        # anyway is discarded (these computations are pure reads).
        from tsunagi.http.v1 import fsrs as fsrs_router

        def compute_that_misses_the_abort(col, req):
            active = next(iter(jobs._jobs.values()))
            jobs.mark_abort_requested(active.id)  # abort lands mid-computation
            return {"params": [1.0], "fsrs_items": 1, "health_check_passed": None}

        monkeypatch.setattr(fsrs_router.f, "compute_params", compute_that_misses_the_abort)
        job_id = submit_compute(client).json()["job_id"]
        body = poll(client, job_id).json()
        assert body["status"] == "aborted"
        assert "discarded" in body["error"]
        assert body["result"] is None


@pytest.mark.skipif(not HAS_SIMULATOR, reason="simulator is 26.08-only")
class TestSimulator:
    BODY = {"deck_size": 100, "days_to_simulate": 30,
            "new_limit": 10, "review_limit": 200, "max_interval": 36500}

    def test_simulate_shapes(self, client):
        response = client.post("/v1/fsrs:simulate", json=self.BODY)
        body = response.json()
        if "weights" in signature(RustBackend.simulate_fsrs_review).parameters:
            # 24.06 requires review history even with a synthetic deck_size.
            assert response.status_code == 400
            assert "at least 400 reviews" in body["detail"]
            return
        assert response.status_code == 200
        assert len(body["daily_review_count"]) == 30
        assert len(body["daily_new_count"]) == 30
        assert body["daily_new_count"][0] == 10

    @pytest.mark.skipif(not HAS_WORKLOAD, reason="workload is unsupported")
    def test_workload_is_keyed_by_retention_percent(self, client):
        body = client.post("/v1/fsrs:simulate-workload", json=self.BODY).json()
        assert body["cost"]
        assert all(50 <= int(k) <= 100 for k in body["cost"])

    @pytest.mark.skipif(not HAS_RETENTION, reason="simulator retention is unsupported")
    def test_optimal_retention_is_a_probability(self, client):
        body = client.post("/v1/fsrs:optimal-retention",
                           json={**self.BODY, "days_to_simulate": 365}).json()
        assert 0.0 < body["retention"] < 1.0

    def test_unsimulatable_setup_is_ankis_400(self, client):
        resp = client.post("/v1/fsrs:simulate", json={"days_to_simulate": 10})
        assert resp.status_code == 400
        expected = ("at least 400 reviews" if "weights" in signature(RustBackend.simulate_fsrs_review).parameters
                    else "no cards to simulate")
        assert expected in resp.json()["detail"]


@pytest.mark.skipif(HAS_SIMULATOR, reason="asserts the 23.10 refusal")
class TestSimulatorUnsupported:
    def test_all_three_routes_are_501(self, client):
        for verb in ("simulate", "simulate-workload", "optimal-retention"):
            resp = client.post(f"/v1/fsrs:{verb}", json={"deck_size": 10})
            assert resp.status_code == 501, verb
            assert "Anki version" in resp.json()["detail"]


@pytest.mark.parametrize("path,supported", [
    ("simulate-workload", HAS_WORKLOAD),
    ("optimal-retention", HAS_RETENTION),
])
def test_missing_simulator_operation_is_501(client, path, supported):
    if supported:
        pytest.skip("operation is supported")
    assert client.post(f"/v1/fsrs:{path}", json={}).status_code == 501
