from typing import Any

from ...adapters.anki.reviews import (
    find_review_ids,
    get_reviews_by_ids,
    get_reviews_of_cards,
)
from ...shared.planning import IndexSpec, SearchSpec, SourceCaps
from ...shared.route_factory import ModelRow, create_resource_routes, make_id_getter
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
    # No MutationCaps. The revlog is append-only history and the scheduler owns
    # it; writing rows here is AnkiConnect's insertReviews, which bypasses the
    # scheduler and is out of scope by decision.
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
        "cards this matches\" - the revlog itself is not searchable. Read-only: "
        "reviews are recorded by the scheduler."
    ),
)
