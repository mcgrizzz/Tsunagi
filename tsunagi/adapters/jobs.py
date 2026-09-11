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
from dataclasses import dataclass
from typing import Any, Dict, Optional

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

    def fail(self, job_id: str, error: str, *, aborted: bool = False) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "aborted" if aborted else "failed"
                job.error = error

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
