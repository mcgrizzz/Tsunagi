"""
In-memory registry for FSRS computations and package imports.

The first cross-request state in Tsunagi, so it copies the Settings shape: a
module singleton guarded by a lock, touched from request threads and Qt-main
op callbacks alike. Jobs are ephemeral by design - nothing is persisted, and
a dev reload empties the store.

One job may be queued/running at a time. That is not a simplification: Anki's
progress (col.latest_progress) and cancellation (col.set_wants_abort) are
global to the backend, so concurrent computations could not be told apart or
aborted individually anyway. Import jobs share this slot so a pending FSRS
abort cannot target an import; imports themselves do not support API abort.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from ..shared.errors import JobConflictError

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("done", "failed", "aborted")
MAX_JOBS = 20


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    result: Optional[Any] = None
    error: Optional[str] = None
    # Abort intent, tracked here because Anki's backend flag is lossy: the
    # rust ThrottlingProgressHandler CLEARS want_abort when a computation
    # starts, so an abort raised before the op reaches the backend vanishes.
    abort_requested: bool = False
    # Set when the job ends. A route that waits for it answers with the
    # failure as raised, so it maps to the same status as without a job.
    ended: threading.Event = field(default_factory=threading.Event, repr=False)
    exception: Optional[BaseException] = field(default=None, repr=False)


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}  # insertion-ordered

    def create(self, kind: str) -> Job:
        with self._lock:
            for job in self._jobs.values():
                if job.status in ACTIVE_STATUSES:
                    raise JobConflictError(
                        f"job {job.id} ({job.kind}) is already {job.status}; "
                        "wait for it to finish"
                    )
            # Keep the store bounded: drop the oldest finished jobs.
            finished = [j for j in self._jobs.values() if j.status in TERMINAL_STATUSES]
            for stale in finished[:max(0, len(finished) - (MAX_JOBS - 1))]:
                del self._jobs[stale.id]
            job = Job(id=uuid.uuid4().hex[:12], kind=kind)
            self._jobs[job.id] = job
            return job

    def start(self, kind: str, submit: Callable[[Job], None]) -> Job:
        """
        Create a job and hand it to `submit`, which starts its work, as one
        step of the request's write (ops.recorded): a retry with the same
        Idempotency-Key gets the same job, and nothing is submitted twice.
        """
        from . import ops

        def begin(ok: Callable[[Any], None], fail: Callable[[BaseException], None]) -> None:
            try:
                job = self.create(kind)
            except BaseException as exc:
                fail(exc)
                return
            try:
                submit(job)
            except BaseException as exc:
                self.fail(job.id, str(exc), exception=exc)
                fail(exc)
                return
            ok(job)

        # A job that failed is started again, as a failed write runs again.
        return ops.recorded(begin, rerun_if=lambda job: job.status in ("failed", "aborted"))

    def wait(self, job: Job, timeout: float) -> bool:
        """True if the job ended within `timeout` seconds."""
        return job.ended.wait(timeout)

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.status == "queued":
                job.status = "running"

    def finish(self, job_id: str, result: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "done"
                job.result = result
                job.ended.set()

    def fail(self, job_id: str, error: str, *, aborted: bool = False,
             exception: Optional[BaseException] = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "aborted" if aborted else "failed"
                job.error = error
                job.exception = exception
                job.ended.set()

    def mark_abort_requested(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.abort_requested = True

    def abort_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return job is not None and job.abort_requested

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        """A plain-dict copy safe to hand to a response model."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {"id": job.id, "kind": job.kind, "status": job.status,
                    "result": job.result, "error": job.error}

    def reset(self) -> None:
        """Test helper - drop everything."""
        with self._lock:
            self._jobs.clear()


# Module singleton, mirroring adapters.settings.settings.
jobs = JobStore()
