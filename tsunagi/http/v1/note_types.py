import time
from functools import partial

from fastapi import Body

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
    find_and_replace_in_models,
    get_model_ids,
    get_model_names_and_counts,
    get_model_names_and_ids,
    get_models_by_ids,
    get_models_by_names,
    patch_field,
    patch_model,
    patch_template,
    reorder_fields,
    reorder_templates,
)
from ...shared.errors import handle_mutation_errors
from ...shared.permissions import requires
from ...shared.planning import (
    IndexSpec,
    MutationCaps,
    ScanSpec,
    SourceCaps,
    SubresourceMutations,
)
from ...shared.route_factory import create_resource_routes, make_id_getter
from ...shared.schemas.models import (
    FieldCreate,
    FieldPatch,
    FindReplaceRequest,
    FindReplaceResult,
    NoteTypeCreate,
    NoteTypeInfo,
    NoteTypePatch,
    TemplateCreate,
    TemplatePatch,
)

mutation_caps = MutationCaps(
    create=create_model,
    create_body=NoteTypeCreate,
    patch=patch_model,
    patch_body=NoteTypePatch,
    delete=delete_model,
    subresources={
        "fields": SubresourceMutations(
            json_key="flds",
            path_name="fields",
            id_field="name",
            id_type="str",
            create=create_field,
            create_body=FieldCreate,
            patch=patch_field,
            patch_body=FieldPatch,
            delete=delete_field,
            reorder=reorder_fields,
        ),
        "templates": SubresourceMutations(
            json_key="tmpls",
            path_name="templates",
            id_field="name",
            id_type="str",
            create=create_template,
            create_body=TemplateCreate,
            patch=patch_template,
            patch_body=TemplatePatch,
            delete=delete_template,
            reorder=reorder_templates,
        ),
    }
)

caps = SourceCaps(
    scan=ScanSpec(find_ids=get_model_ids, hydrate=partial(get_models_by_ids, include_counts=True)),
    indices=[
        # Faster simply because we don't call get() on all models
        IndexSpec(
            path=("id",),
            fetch_values=partial(get_models_by_ids, include_counts=True),
            coerce=lambda v: int(v) if isinstance(v, (int, str)) and str(v).isdigit() else None
        ),
        # Same as above but 1 total extra query
        IndexSpec(
            path=("name",),
            fetch_values=lambda xs, wants=None: get_models_by_names(
                [str(x) for x in xs if x is not None], wants, include_counts=True
            ),
        ),
    ],
    columns_fetchers={
        frozenset({"id", "name"}): get_model_names_and_ids,  # Fastest because this only runs 1 SQL query under the hood
        frozenset({"id", "name", "note_count"}): get_model_names_and_counts,
    },
    mutations=mutation_caps,
)

# Creates comprehensive note type endpoints:
# Query: GET /v1/note-types, POST /v1/note-types/query
# Top-level: POST /v1/note-types, PATCH /v1/note-types/{id}, DELETE /v1/note-types/{id}
# Fields: POST/PATCH/DELETE /v1/note-types/{note_type_id}/fields/..., PUT /v1/note-types/{note_type_id}/fields:order
# Templates: POST/PATCH/DELETE /v1/note-types/{note_type_id}/templates/..., PUT /v1/note-types/{note_type_id}/templates:order
router = create_resource_routes(
    path="/v1/note-types",
    caps=caps,
    row_model=NoteTypeInfo,
    id_getter=make_id_getter("id"),
    resource_name="note_type",
    resource_plural="note_types",
    permission_resource="note_types",
    tag="Note Types",
    description="Note types define the structure of cards in Anki. Select note_count "
                "for the live number of notes using each type across all decks, or "
                "filter with where=note_count>0. Counts are included in full native "
                "query results; name/ID-only queries do not calculate them."
)


@router.post(
    "/v1/note-types:find-replace",
    openapi_extra=requires("write:notes"),
    response_model=FindReplaceResult,
    summary="Find and replace across templates and styling",
    description="Literal (not regex) replacement in card templates and CSS. Name one note type by `note_type_id` or `note_type_name`, or omit both to sweep every note type. Only note types that actually contained the text are touched or counted.",
    tags=["Note Types"],
    operation_id="noteTypesFindReplace",
)
@handle_mutation_errors("find-replace")
def find_replace(body: FindReplaceRequest = Body(...)) -> FindReplaceResult:
    start = time.perf_counter()
    affected = find_and_replace_in_models(
        body.find, body.replace, body.note_type_name, body.front, body.back, body.css,
        note_type_id=body.note_type_id,
    )
    return FindReplaceResult(
        affected=affected,
        stats={"duration_ms": round((time.perf_counter() - start) * 1000, 3)},
    )
