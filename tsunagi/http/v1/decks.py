from ...adapters.anki.decks import (
    create_deck,
    delete_deck,
    get_deck_names_and_ids,
    get_decks_by_ids,
    get_decks_by_names,
    list_decks,
    patch_deck,
)
from ...shared.planning import IndexSpec, MutationCaps, SourceCaps
from ...shared.route_factory import ModelRow, create_resource_routes, make_id_getter
from ...shared.schemas.wrappers import Paginated

mutation_caps = MutationCaps(
    create=create_deck,
    patch=patch_deck,
    delete=delete_deck,
)

caps = SourceCaps(
    fetch_all=list_decks,
    indices=[
        IndexSpec(
            path=("id",),
            fetch_values=get_decks_by_ids,
            coerce=lambda v: int(v) if isinstance(v, (int, str)) and str(v).isdigit() else None
        ),
        IndexSpec(
            path=("name",),
            fetch_values=lambda xs: get_decks_by_names(
                [str(x) for x in xs if x is not None]
            ),
        ),
    ],
    columns_fetchers={
        frozenset({"id", "name"}): get_deck_names_and_ids,  # single backend query
    },
    mutations=mutation_caps,
)

# Query: GET /v1/decks, POST /v1/decks/query
# Mutations: POST /v1/decks, PATCH /v1/decks/{deck_id}, DELETE /v1/decks/{deck_id}
router = create_resource_routes(
    path="/v1/decks",
    caps=caps,
    response_model=Paginated[ModelRow],
    id_getter=make_id_getter("id"),
    resource_name="deck",
    resource_plural="decks",
    tag="Decks",
    description="Deck hierarchy (nested names use '::'). Filtered (dynamic) decks appear in reads; mutations operate on normal decks."
)
