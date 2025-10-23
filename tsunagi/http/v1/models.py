from ...shared.route_factory import ModelRow, create_resource_routes, make_id_getter
from ...shared.planning import IndexSpec, MutationCaps, SourceCaps
from ...shared.schemas.wrappers import Paginated
from ...adapters.anki.models import create_model, get_model_names_and_ids, get_models_by_ids, get_models_by_names, list_models


mutation_caps = MutationCaps(
    create=create_model
)

caps = SourceCaps(
    fetch_all = list_models,
    indices=[
        # Faster simply because we don't call get() on all models
        IndexSpec(
            path=("id",),
            fetch_values=get_models_by_ids,
            coerce=lambda v: int(v) if isinstance(v, (int, str)) and str(v).isdigit() else None
        ),
        # Same as above but 1 total extra query
        IndexSpec(
            path=("name",),
            fetch_values=lambda xs: get_models_by_names(
                [str(x) for x in xs if x is not None]
            ),
        ),
    ],
    columns_fetchers={
        frozenset({"id", "name"}): get_model_names_and_ids,  # Fastest because this only runs 1 SQL query under the hood
    },
    mutations=mutation_caps,
)

# Creates GET /v1/models and POST /v1/models/query
# mutations when we add them 
router = create_resource_routes(
    path="/v1/models",
    caps=caps,
    response_model=Paginated[ModelRow],
    id_getter=make_id_getter("id"),
)
