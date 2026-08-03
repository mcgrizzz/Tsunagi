from typing import Any

from ...adapters.anki.deck_configs import (
    create_deck_config,
    delete_deck_config,
    get_deck_configs_by_ids,
    list_deck_configs,
    patch_deck_config,
)
from ...shared.planning import IndexSpec, MutationCaps, SourceCaps
from ...shared.route_factory import ModelRow, create_resource_routes, make_id_getter
from ...shared.schemas.wrappers import Paginated


def _int_id(v: Any) -> Any:
    return int(v) if isinstance(v, (int, str)) and str(v).isdigit() else None


caps = SourceCaps(
    fetch_all=list_deck_configs,
    indices=[IndexSpec(path=("id",), fetch_values=get_deck_configs_by_ids, coerce=_int_id)],
    mutations=MutationCaps(
        create=create_deck_config,
        patch=patch_deck_config,
        delete=delete_deck_config,
    ),
)

# Query: GET /v1/deck-configs, POST /v1/deck-configs/query
# Mutations: POST /v1/deck-configs, PATCH|DELETE /v1/deck-configs/{deck_config_id}
router = create_resource_routes(
    path="/v1/deck-configs",
    caps=caps,
    response_model=Paginated[ModelRow],
    id_getter=make_id_getter("id"),
    resource_name="deck_config",
    resource_plural="deck_configs",
    tag="Deck Configs",
    description="Deck options groups. Rows are Anki's config dicts verbatim, so newer scheduler keys survive a read-modify-write. Assign one to a deck with PATCH /v1/decks/{id} {config_id}.",
)
