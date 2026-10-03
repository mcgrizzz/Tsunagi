import time
from collections import Counter
from typing import Any

from fastapi import Body

from ...adapters.anki.reviews import (
    COLUMNS,
    REVIEW_SQL,
    existing_review_ids,
    find_review_ids,
    get_reviews_by_ids,
    get_reviews_of_cards,
    insert_reviews,
    ordered_review_ids,
    page_review_ids,
    search_review_rows,
)
from ...shared.errors import ConflictError, handle_mutation_errors
from ...shared.permissions import requires
from ...shared.planning import IndexSpec, OrderSpec, SearchSpec, SourceCaps
from ...shared.route_factory import create_resource_routes, make_id_getter
from ...shared.schemas.reviews import (
    InsertReviewsRequest,
    InsertReviewsResult,
    ReviewInfo,
)


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
    # page_ids: a bare or where-filtered listing walks the revlog primary key
    # keyset-style (~1ms/page) instead of materializing every id (~63ms on a
    # 120k-review collection). A `search=` query still enumerates in full -
    # Anki search has no keyset form.
    search=SearchSpec(find_ids=find_review_ids, hydrate=get_reviews_by_ids,
                      page_ids=page_review_ids, rows=search_review_rows),
    # Every review field is a column: where clauses go into the id query (backlog 9.13).
    sql=REVIEW_SQL,
    # order= sorts by any review field in SQL; Anki doesn't sort reviews (backlog 8.1).
    order=OrderSpec(names=lambda: list(REVIEW_SQL.columns), documented=tuple(REVIEW_SQL.columns),
                    ordered_ids=ordered_review_ids,
                    by_column=True),
    # No MutationCaps: the factory's CRUD shapes don't fit an append-only log.
    # The one write - raw row insertion for history imports, AnkiConnect's
    # insertReviews - is the hand-written POST below.
)

# Query: GET /v1/reviews (?search=...), POST /v1/reviews/query
router = create_resource_routes(
    path="/v1/reviews",
    caps=caps,
    row_model=ReviewInfo,
    id_getter=make_id_getter("id"),
    resource_name="review",
    resource_plural="reviews",
    permission_resource="reviews",
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
    openapi_extra=requires("write:reviews"),
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
    # A taken id would fail the insert with a database error (a 500); name it
    # instead. The AnkiConnect shim keeps upstream's error text.
    ids = [r.id for r in body.reviews]
    taken = sorted({i for i, n in Counter(ids).items() if n > 1} | set(existing_review_ids(ids)))
    if taken:
        raise ConflictError(f"Review ids already taken: {', '.join(map(str, taken))}; "
                              "nothing was inserted")
    inserted = insert_reviews(
        [[getattr(r, f) for f in field_names] for r in body.reviews])
    return InsertReviewsResult(
        inserted=inserted,
        stats={"duration_ms": round((time.perf_counter() - start) * 1000, 3)},
    )
