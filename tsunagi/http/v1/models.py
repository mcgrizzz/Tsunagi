from ...adapters.anki.models import (
    # Field subresource mutations
    create_field,
    # Top-level mutations
    create_model,
    # Template subresource mutations
    create_template,
    delete_field,
    delete_model,
    delete_template,
    get_model_names_and_ids,
    get_models_by_ids,
    get_models_by_names,
    # Query operations
    list_models,
    patch_field,
    patch_model,
    patch_template,
    reorder_fields,
    reorder_templates,
)
from ...shared.planning import IndexSpec, MutationCaps, SourceCaps, SubresourceMutations
from ...shared.route_factory import ModelRow, create_resource_routes, make_id_getter
from ...shared.schemas.wrappers import Paginated

mutation_caps = MutationCaps(
    create=create_model,
    patch=patch_model,
    delete=delete_model,
    subresources={
        "fields": SubresourceMutations(
            json_key="flds",
            path_name="fields",
            id_field="name",
            id_type="str",
            create=create_field,
            patch=patch_field,
            delete=delete_field,
            reorder=reorder_fields,
        ),
        "templates": SubresourceMutations(
            json_key="tmpls",
            path_name="templates",
            id_field="name",
            id_type="str",
            create=create_template,
            patch=patch_template,
            delete=delete_template,
            reorder=reorder_templates,
        ),
    }
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

# Creates comprehensive model endpoints:
# Query: GET /v1/models, POST /v1/models/query
# Top-level: POST /v1/models, PATCH /v1/models/{model_id}, DELETE /v1/models/{model_id}
# Fields: POST/PATCH/DELETE /v1/models/{model_id}/fields/..., PUT /v1/models/{model_id}/fields:order
# Templates: POST/PATCH/DELETE /v1/models/{model_id}/templates/..., PUT /v1/models/{model_id}/templates:order
router = create_resource_routes(
    path="/v1/models",
    caps=caps,
    response_model=Paginated[ModelRow],
    id_getter=make_id_getter("id"),
    resource_name="model",
    resource_plural="models",
    tag="Models",
    description="Note types define the structure of cards in Anki."
)
