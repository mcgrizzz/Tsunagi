"""
Statistics (6.6): today's numbers, and the days studied as a list resource, as
Anki's Statistics screen counts them. Read-only; they come from review history,
so read:reviews.
"""
import time

from fastapi import Query

from ...adapters.anki.statistics import review_days, today_statistics
from ...shared.errors import handle_mutation_errors
from ...shared.permissions import requires
from ...shared.planning import SourceCaps
from ...shared.route_factory import create_resource_routes
from ...shared.schemas.statistics import ReviewDay, TodayStatistics

# GET /v1/review-days, POST /v1/review-days/query: every shared parameter
# (where=date>="2026-01-01", order=date:desc, include=total, limit, cursor).
# `search` decides what the rows count, so the source is `searched`.
router = create_resource_routes(
    path="/v1/review-days",
    caps=SourceCaps(searched=review_days, key_type=str),
    row_model=ReviewDay,
    id_getter=lambda row: row["date"],
    resource_name="review_day",
    resource_plural="review_days",
    tag="Statistics",
    permission_resource="reviews",
    description=("One row per Anki day with reviews: what a heatmap needs. `search` counts only "
                 "the reviews of the cards an Anki search finds (a deck, a tag...); without it, "
                 "the whole collection. include=total is the number of days studied."),
)


@router.get(
    "/v1/statistics/today",
    openapi_extra=requires("read:reviews"),
    response_model=TodayStatistics,
    summary="Today's statistics",
    description=("Anki's day so far, as its Statistics screen's Today section counts it: cards "
                 "answered, time, correct answers, by kind, and mature cards; and the current "
                 "streak of days with reviews."),
    tags=["Statistics"],
    operation_id="getTodayStatistics",
)
@handle_mutation_errors("statistics")
def today(search: str = Query("", description=(
        "Anki search: only reviews of the cards it finds count, e.g. `deck:Japanese` or "
        "`tag:verbs`. Empty: the whole collection."))) -> dict:
    start = time.perf_counter()
    return {**today_statistics(search),
            "stats": {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}}
