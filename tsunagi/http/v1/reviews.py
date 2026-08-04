import time
from typing import Any

from fastapi import Body

from ...adapters.anki.reviews import (
    COLUMNS,
    find_review_ids,
    get_reviews_by_ids,
    get_reviews_of_cards,
    insert_reviews,
)
from ...shared.errors import handle_mutation_errors
from ...shared.planning import IndexSpec, SearchSpec, SourceCaps
from ...shared.route_factory import ModelRow, create_resource_routes, make_id_getter
from ...shared.schemas.reviews import InsertReviewsRequest, InsertReviewsResult
from ...shared.schemas.wrappers import Paginated


def _int_id(v: Any) -> Any:
    return int(v) if isinstance(v, (int, str)) and str(v).isdigit() else None


caps = SourceCaps(
    # No fetch_all, for the same reason cards and notes have none: it puts the
    # planner on the "full" tier, which materializes every row to return a
    # page. A mature revlog is hundreds of thousands of rows, so a bare listing
    # took over a second to hand back five. The search tier enumerates ids and
    # hydrates one page.
    indices=[
        IndexSpec(path=("id",), fetch_values=get_reviews_by_ids, coerce=_int_id),
        IndexSpec(path=("card_id",), fetch_values=get_reviews_of_cards, coerce=_int_id),
    ],
    search=SearchSpec(find_ids=find_review_ids, hydrate=get_reviews_by_ids),
    # No MutationCaps: the factory's CRUD shapes don't fit an append-only log.
    # The one write - raw row insertion for history imports, AnkiConnect's
    # insertReviews - is the hand-written POST below.
)

# Query: GET /v1/reviews (?search=...), POST /v1/reviews/query
router = create_resource_routes(
    path="/v1/reviews",
    caps=caps,
    response_model=Paginated[ModelRow],
    id_getter=make_id_getter("id"),
    resource_name="review",
    resource_plural="reviews",
    tag="Reviews",
    description=(
        "Review history from the revlog, newest last. `id` is the review's "
        "epoch-ms timestamp and its identity, so pages come back in review "
        "order. `search` takes Anki query syntax and means \"reviews of the "
        "cards this matches\" - the revlog itself is not searchable. Reviews "
        "are recorded by the scheduler; POST inserts raw rows for history "
        "imports."
    ),
)


@router.post(
    "/v1/reviews",
    response_model=InsertReviewsResult,
    summary="Insert raw review rows",
    description=(
        "Appends rows to the revlog behind the scheduler's back - "
        "AnkiConnect's insertReviews, meant for importing review history. "
        "Rows use the same fields GET returns (aliases accepted); `id` is the "
        "review's epoch-ms timestamp and must be unique. All rows land in one "
        "transaction or none do. Side effects inherent to a raw revlog write: "
        "the undo history and cached study queues are discarded, and no event "
        "is emitted."
    ),
    tags=["Reviews"],
    operation_id="createReviews",
)
@handle_mutation_errors("insert reviews")
def create_reviews(body: InsertReviewsRequest = Body(...)) -> InsertReviewsResult:
    start = time.perf_counter()
    field_names = ("id", "card_id", "usn", "ease", "interval",
                   "last_interval", "factor", "time_ms", "type")
    assert len(field_names) == len(COLUMNS)
    inserted = insert_reviews(
        [[getattr(r, f) for f in field_names] for r in body.reviews])
    return InsertReviewsResult(
        inserted=inserted,
        stats={"duration_ms": round((time.perf_counter() - start) * 1000, 3)},
    )
