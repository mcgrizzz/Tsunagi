"""
Unit tests for the job store - pure stdlib, no collection needed.
"""
import pytest

from tsunagi.adapters.jobs import MAX_JOBS, JobStore
from tsunagi.shared.errors import JobConflictError


@pytest.fixture()
def store():
    return JobStore()


class TestLifecycle:
    def test_create_starts_queued(self, store):
        job = store.create("compute_params")
        assert job.status == "queued"
        assert store.get(job.id).kind == "compute_params"

    def test_running_then_done(self, store):
        job = store.create("compute_params")
        store.mark_running(job.id)
        assert store.get(job.id).status == "running"
        store.finish(job.id, {"params": [1.0]})
        got = store.get(job.id)
        assert got.status == "done"
        assert got.result == {"params": [1.0]}
        assert got.error is None

    def test_failed_vs_aborted(self, store):
        a = store.create("compute_params")
        store.fail(a.id, "Insufficient review history")
        assert store.get(a.id).status == "failed"

        b = store.create("compute_params")
        store.fail(b.id, "Interrupted", aborted=True)
        assert store.get(b.id).status == "aborted"

    def test_snapshot_is_a_plain_dict(self, store):
        job = store.create("evaluate_params")
        snap = store.snapshot(job.id)
        assert snap == {"id": job.id, "kind": "evaluate_params",
                        "status": "queued", "result": None, "error": None}

    def test_unknown_id(self, store):
        assert store.get("nope") is None
        assert store.snapshot("nope") is None
        # Terminal-state writes on unknown ids are silently ignored.
        store.finish("nope", {})
        store.fail("nope", "x")
        store.mark_abort_requested("nope")
        assert store.abort_requested("nope") is False

    def test_abort_intent_is_recorded(self, store):
        job = store.create("compute_params")
        assert store.abort_requested(job.id) is False
        store.mark_abort_requested(job.id)
        assert store.abort_requested(job.id) is True
        # Intent is internal bookkeeping - not part of the wire snapshot.
        assert "abort_requested" not in store.snapshot(job.id)


class TestSingleSlot:
    def test_second_active_job_conflicts(self, store):
        first = store.create("compute_params")
        with pytest.raises(JobConflictError) as e:
            store.create("evaluate_params")
        assert first.id in str(e.value)

    def test_running_job_also_conflicts(self, store):
        job = store.create("compute_params")
        store.mark_running(job.id)
        with pytest.raises(JobConflictError):
            store.create("compute_params")

    def test_free_after_terminal(self, store):
        for end in (lambda j: store.finish(j, {}),
                    lambda j: store.fail(j, "x"),
                    lambda j: store.fail(j, "x", aborted=True)):
            job = store.create("compute_params")
            end(job.id)
            # No raise: the slot is free again.
        assert store.create("compute_params")


class TestEviction:
    def test_finished_jobs_are_bounded(self, store):
        seen = []
        for _ in range(MAX_JOBS + 5):
            job = store.create("compute_params")
            store.finish(job.id, {})
            seen.append(job.id)
        assert len(store._jobs) == MAX_JOBS
        # Newest survive; the overflow was trimmed from the oldest end.
        assert store.get(seen[-1]) is not None
        assert store.get(seen[0]) is None
