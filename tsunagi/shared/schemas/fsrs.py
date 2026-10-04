"""
Schemas for the native FSRS surface. Native-only: AnkiConnect exposes no FSRS,
so there are no wire-name aliases to carry.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .wrappers import NULLABLE, RequestBody

# ----------------- Jobs -----------------


class JobProgress(BaseModel):
    current: int
    total: int


JobStatus = Literal["queued", "running", "done", "failed", "aborted"]


class JobInfo(BaseModel):
    id: str
    kind: str
    status: JobStatus
    progress: Optional[JobProgress] = Field(
        None, description="Best-effort progress, only while running; null otherwise", **NULLABLE)
    result: Optional[Dict[str, Any]] = Field(
        None, description="When done: the result, shaped by the job's kind (see the route that started it); "
                          "null before", **NULLABLE)
    error: Optional[str] = Field(None, description="When failed or aborted: why; null otherwise", **NULLABLE)
    stats: dict


class JobSubmitted(BaseModel):
    job_id: str
    status: JobStatus
    stats: dict


# ----------------- Requests -----------------


class ComputeParamsRequest(RequestBody):
    search: str = ""
    current_params: Optional[List[float]] = None
    ignore_revlogs_before_ms: Optional[int] = None
    num_of_relearning_steps: Optional[int] = None
    health_check: Optional[bool] = None


class EvaluateParamsRequest(RequestBody):
    params: List[float]
    search: str = ""
    ignore_revlogs_before_ms: Optional[int] = None


class SimulateRequest(RequestBody):
    """
    Raw passthrough to Anki's SimulateFsrsReviewRequest; omitted limits stay at
    the protobuf default 0, and Anki itself rejects an unsimulatable setup
    ("no cards to simulate"), so there are no invented defaults here. Empty
    `params` means Anki's built-in FSRS defaults.
    """
    params: List[float] = []
    desired_retention: float = 0.9
    deck_size: int = 0
    days_to_simulate: int = 365
    new_limit: int = 0
    review_limit: int = 0
    max_interval: int = 0
    search: str = ""


# ----------------- Synchronous verb responses -----------------


class SimulateResult(BaseModel):
    accumulated_knowledge_acquisition: List[float]
    daily_review_count: List[int]
    daily_new_count: List[int]
    daily_time_cost: List[float]
    stats: dict


class WorkloadResult(BaseModel):
    """Maps keyed by desired-retention percent, as Anki returns them."""
    cost: Dict[int, float]
    memorized: Dict[int, float]
    # Scalar: cards still memorized at the end with no further reviews.
    reviewless_end_memorized: float
    review_count: Dict[int, float]
    stats: dict


class OptimalRetentionResult(BaseModel):
    retention: float
    stats: dict
