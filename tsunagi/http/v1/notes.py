import time

from fastapi import Body

from ...adapters.anki.note_batches import create_notes
from ...adapters.anki.notes import (
    check_notes,
    create_note,
    delete_notes,
    find_note_ids,
    get_notes_by_ids,
    page_note_ids,
    patch_note,
)
from ...shared.errors import handle_mutation_errors
from ...shared.planning import IndexSpec, MutationCaps, SearchSpec, SourceCaps
from ...shared.route_factory import ModelRow, create_resource_routes, make_id_getter
from ...shared.schemas.notes import (
    NoteBatchCreateRequest,
    NoteBatchCreateResponse,
    NoteCheckRequest,
    NoteCheckResponse,
)
from ...shared.schemas.wrappers import Paginated

caps = SourceCaps(
    # No fetch_all on purpose: materializing every note must be unreachable.
    # A bare GET /v1/notes routes through the scan tier, which pages ids
    # keyset-style (page_ids below) and hydrates one page at a time.
    indices=[
        IndexSpec(
            path=("id",),
            fetch_values=get_notes_by_ids,
            coerce=lambda v: int(v) if isinstance(v, (int, str)) and str(v).isdigit() else None
        ),
    ],
    # No columns_fetchers: no backend route returns a cheaper subset of a note.
    # page_ids: bare and where-filtered listings walk the notes primary key
    # keyset-style instead of materializing every note id per page request.
    # A `search=` query still enumerates in full - Anki search has no keyset.
    search=SearchSpec(find_ids=find_note_ids, hydrate=get_notes_by_ids,
                      page_ids=page_note_ids),
    mutations=MutationCaps(
        create=create_note,
        patch=patch_note,
        delete=lambda nid: delete_notes([nid]) > 0,
    ),
)

# Query: GET /v1/notes (?search=...), POST /v1/notes/query
# Mutations: POST /v1/notes, PATCH /v1/notes/{note_id}, DELETE /v1/notes/{note_id}
router = create_resource_routes(
    path="/v1/notes",
    caps=caps,
    response_model=Paginated[ModelRow],
    id_getter=make_id_getter("id"),
    resource_name="note",
    resource_plural="notes",
    tag="Notes",
    description="Notes hold the content; cards are generated from them by a model's templates. Use `search` for Anki query syntax."
)


@router.post(
    "/v1/notes:check",
    response_model=NoteCheckResponse,
    summary="Check whether notes can be added",
    description="Reports per candidate whether it can be added, and why not (empty first field, duplicate, unknown model/deck). Adds nothing.",
    tags=["Notes"],
    operation_id="checkNotes",
)
@handle_mutation_errors("check")
def check(body: NoteCheckRequest = Body(..., description="Candidate notes")) -> NoteCheckResponse:
    start = time.perf_counter()
    results = check_notes([n.dict(by_alias=True) for n in body.notes])
    return NoteCheckResponse(
        results=results,
        stats={"duration_ms": round((time.perf_counter() - start) * 1000, 3)},
    )


@router.post(
    "/v1/notes:batch-create",
    response_model=NoteBatchCreateResponse,
    summary="Create multiple notes",
    description=(
        "Processes notes in input order. Valid notes are saved even when another note is rejected. "
        "Returns created note/card IDs and failures, each with its zero-based input index. "
        "Duplicates include earlier successes in this batch. All successful additions form one undo step. "
        "Malformed request bodies return 422 before any notes are added. "
        "Upload media separately and reference the returned filenames in fields."
    ),
    tags=["Notes"],
    operation_id="batchCreateNotes",
)
@handle_mutation_errors("batch create notes")
def batch_create(body: NoteBatchCreateRequest) -> NoteBatchCreateResponse:
    return create_notes(body.notes)
