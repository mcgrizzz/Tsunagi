"""
Statistics (6.6): today's numbers and the days studied, as Anki's Statistics
screen counts them. Read-only; they come from review history, so read:reviews.
"""
import time

from fastapi import APIRouter, Query

from ...adapters.anki.statistics import review_days, today_statistics
from ...shared.errors import handle_mutation_errors
from ...shared.permissions import requires
from ...shared.schemas.statistics import ReviewDays, TodayStatistics

router = APIRouter()

SEARCH = Query("", description=(
    "Anki search: only reviews of the cards it finds count, e.g. `deck:Japanese` or `tag:verbs`. "
    "Empty: the whole collection."))


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


@router.get(
    "/v1/statistics/today",
    openapi_extra=requires("read:reviews"),
    response_model=TodayStatistics,
    summary="Today's statistics",
    description=("Anki's day so far, as its Statistics screen's Today section counts it: cards "
                 "answered, time, correct answers, by kind, and mature cards."),
    tags=["Statistics"],
    operation_id="getTodayStatistics",
)
@handle_mutation_errors("statistics")
def today(search: str = SEARCH) -> dict:
    start = time.perf_counter()
    return {**today_statistics(search), "stats": _stats(start)}


@router.get(
    "/v1/statistics/review-days",
    openapi_extra=requires("read:reviews"),
    response_model=ReviewDays,
    summary="Days studied",
    description=("One row per Anki day with reviews, newest first, with how many days had "
                 "reviews and the current streak: what a heatmap or a streak counter needs."),
    tags=["Statistics"],
    operation_id="getReviewDays",
)
@handle_mutation_errors("statistics")
def days_studied(search: str = SEARCH,
                 days: int = Query(365, ge=0, le=36500, description=(
                     "How many days back from today, today included; 0 for all history."))) -> dict:
    start = time.perf_counter()
    return {**review_days(search, days), "stats": _stats(start)}
