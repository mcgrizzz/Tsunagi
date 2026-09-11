"""
FSRS computations: optimize/evaluate parameters, and the simulator.

Optimization and evaluation walk the whole review history and can far outlive
op_timeout_seconds, so they are the API's first async jobs: the submit routes
answer 202 with a job id, GET /v1/jobs/{id} polls status/progress/result, and
POST /v1/jobs/{id}:abort cancels through Anki's own abort flag. One job runs
at a time - Anki's progress and abort are global to the backend, so pretending
to queue more would be dishonest (a second submit gets a 409).

The simulator verbs finish in well under a second, so they stay synchronous.
"""
import time
from typing import Callable, Optional

from fastapi import APIRouter, Body

from ...adapters.anki import fsrs as f
from ...adapters.jobs import jobs
from ...adapters.ops import query_op_run_async
from ...shared.errors import (
    JobConflictError,
    ResourceNotFoundError,
    anki_error_detail,
    handle_mutation_errors,
)
from ...shared.schemas.fsrs import (
    ComputeParamsRequest,
    EvaluateParamsRequest,
    JobInfo,
    JobSubmitted,
    OptimalRetentionResult,
    SimulateRequest,
    SimulateResult,
    WorkloadResult,
)

router = APIRouter()


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


def _verb(path: str, summary: str, description: str,
          response_model, status_code: int = 200) -> Callable:
    def decorate(fn: Callable) -> Callable:
        operation_id = "fsrs" + "".join(p.capitalize() for p in path.split("-"))
        return router.post(
            f"/v1/fsrs:{path}",
            response_model=response_model,
            status_code=status_code,
            summary=summary,
            description=description,
            tags=["FSRS"],
            operation_id=operation_id,
        )(handle_mutation_errors(path)(fn))
    return decorate


class _AbortedBeforeStart(Exception):
    """The abort beat the computation to the backend - honored, not raced."""


def _submit(kind: str, run: Callable, start: float) -> JobSubmitted:
    """
    Create the job, then fire the computation without waiting on it. The op
    callbacks (Qt main thread) only flip the job record - nothing blocking.
    """
    job = jobs.create(kind)

    def op(col):
        jobs.mark_running(job.id)
        # Anki's backend clears its global abort flag when a computation
        # starts, so an abort raised between submit and here would be lost.
        # Honor it ourselves before entering the backend.
        if jobs.abort_requested(job.id):
            raise _AbortedBeforeStart("aborted before the computation started")
        return run(col)

    def on_success(result):
        # Anki's abort flag is unreliable around these computations (cleared
        # twice per run, and the revlog-load phase never checks it), so an
        # acknowledged abort could otherwise still end in `done` - a coin-flip
        # contract. These jobs are pure reads, so honoring the abort by
        # discarding the result misreports nothing about the collection.
        if jobs.abort_requested(job.id):
            jobs.fail(job.id, "aborted; the computation had already finished "
                              "and its result was discarded", aborted=True)
        else:
            jobs.finish(job.id, result)

    query_op_run_async(
        op,
        on_success=on_success,
        on_failure=lambda exc: jobs.fail(
            job.id, anki_error_detail(exc),
            aborted=(isinstance(exc, _AbortedBeforeStart)
                     or type(exc).__name__ == "Interrupted")),
    )
    current = jobs.get(job.id)
    return JobSubmitted(
        job_id=job.id,
        status=current.status if current else "queued",
        stats=_stats(start),
    )


# ====================
# Jobs (submit / poll / abort)
# ====================

@_verb("compute-params", "Optimize FSRS parameters",
       "Starts optimizing FSRS parameters from the review history matching "
       "`search` (empty = whole collection) and returns a job id to poll. "
       "Result: `{params, fsrs_items, health_check_passed}`. Options beyond "
       "`search` need a newer Anki than 23.10 (501 there). With too little "
       "history, 23.10 fails the job with Anki's message while newer Anki "
       "reports done with empty params - surfaced as-is, not normalized.",
       response_model=JobSubmitted, status_code=202)
def compute_params(body: Optional[ComputeParamsRequest] = Body(None)) -> JobSubmitted:
    start = time.perf_counter()
    body = body or ComputeParamsRequest()
    f.check_supported(body)
    return _submit("compute_params", lambda col: f.compute_params(col, body), start)


@_verb("evaluate-params", "Evaluate FSRS parameters",
       "Starts evaluating the given parameters against the review history "
       "matching `search`; poll the job for `{log_loss, rmse_bins}`.",
       response_model=JobSubmitted, status_code=202)
def evaluate_params(body: EvaluateParamsRequest = Body(...)) -> JobSubmitted:
    start = time.perf_counter()
    f.check_supported(body)
    return _submit("evaluate_params", lambda col: f.evaluate_params(col, body), start)


@router.get(
    "/v1/jobs/{job_id}",
    response_model=JobInfo,
    summary="Poll a job",
    description="Status, best-effort progress while running, and the result "
                "or error once terminal. Finished jobs are kept in memory "
                "until evicted, not persisted. Import jobs report their result "
                "or error but do not expose progress or support abort.",
    tags=["Jobs"],
    operation_id="getJob",
)
@handle_mutation_errors("job read")
def get_job(job_id: str) -> JobInfo:
    start = time.perf_counter()
    snap = jobs.snapshot(job_id)
    if snap is None:
        raise ResourceNotFoundError("job", job_id)
    progress = None
    if snap["status"] == "running" and snap["kind"] != "import_package":
        # The backend's abort flag is one-shot AND cleared when a computation
        # starts, so a single :abort can lose a race with the op's startup.
        # While an abort is pending, every poll re-raises the flag - the
        # client is polling to see the abort land anyway.
        if jobs.abort_requested(job_id):
            f.request_abort()
        progress = f.read_progress()
    return JobInfo(progress=progress, stats=_stats(start), **snap)


@router.post(
    "/v1/jobs/{job_id}:abort",
    response_model=JobInfo,
    summary="Abort a job",
    description="A 200 here guarantees the job ends `aborted` - poll to "
                "observe it. Anki is asked to stop the computation; if it "
                "finishes anyway (its abort flag has blind spots), the result "
                "is discarded - these computations write nothing, so nothing "
                "is lost but the numbers. 409 if the job already ended or is an "
                "import job, which cannot be aborted through this endpoint.",
    tags=["Jobs"],
    operation_id="abortJob",
)
@handle_mutation_errors("job abort")
def abort_job(job_id: str) -> JobInfo:
    start = time.perf_counter()
    snap = jobs.snapshot(job_id)
    if snap is None:
        raise ResourceNotFoundError("job", job_id)
    if snap["kind"] == "import_package":
        raise JobConflictError("Import jobs cannot be aborted; poll for completion")
    if snap["status"] not in ("queued", "running"):
        raise JobConflictError(f"job {job_id} is already {snap['status']}")
    jobs.mark_abort_requested(job_id)
    f.request_abort()
    return JobInfo(progress=None, stats=_stats(start), **jobs.snapshot(job_id))


# ====================
# Simulator (26.08+; 501 on older Anki)
# ====================

_SIM_NOTE = ("Fields pass through to Anki's simulator verbatim; give real "
             "limits (deck_size, new_limit, review_limit, days_to_simulate) "
             "or Anki refuses with 'no cards to simulate'. Empty `params` "
             "means Anki's built-in FSRS defaults. Needs a newer Anki than "
             "23.10 (501 there).")


@_verb("simulate", "Simulate a review workload",
       "Per-day review/new counts, time cost and knowledge acquisition for "
       "the simulated schedule. " + _SIM_NOTE,
       response_model=SimulateResult)
def simulate(body: SimulateRequest = Body(...)) -> SimulateResult:
    start = time.perf_counter()
    return SimulateResult(stats=_stats(start), **f.simulate(body))


@_verb("simulate-workload", "Compare workload across retentions",
       "Cost, memorized counts and review counts keyed by desired-retention "
       "percent. " + _SIM_NOTE,
       response_model=WorkloadResult)
def simulate_workload(body: SimulateRequest = Body(...)) -> WorkloadResult:
    start = time.perf_counter()
    return WorkloadResult(stats=_stats(start), **f.simulate_workload(body))


@_verb("optimal-retention", "Compute optimal retention",
       "The desired retention minimizing total workload for this setup. "
       + _SIM_NOTE,
       response_model=OptimalRetentionResult)
def optimal_retention(body: SimulateRequest = Body(...)) -> OptimalRetentionResult:
    start = time.perf_counter()
    return OptimalRetentionResult(retention=f.optimal_retention(body), stats=_stats(start))
