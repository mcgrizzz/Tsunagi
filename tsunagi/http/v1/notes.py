import time
from typing import List, Literal, Optional, Union

from fastapi import Body, Query

from ...adapters.anki.note_batches import create_notes
from ...adapters.anki.notes import (
    check_notes,
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
    NoteCheckRequest,
    NoteCheckResponse,
    NoteCreate,
    NoteCreateResponse,
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
    description=("Reports per candidate whether it can be added, and why not (empty first field, "
                 "duplicate, unknown model/deck). Adds nothing. Duplicate note IDs are included "
                 "by default. Set include_duplicate_ids=false to skip their lookup; "
                 "duplicate_note_ids is then null, while validation and duplicate policy are unchanged."),
    tags=["Notes"],
    operation_id="checkNotes",
)
@handle_mutation_errors("check")
def check(
    body: NoteCheckRequest = Body(..., description="Candidate notes"),
    include_duplicate_ids: bool = Query(default=True, description="Look up matching duplicate note IDs"),
) -> NoteCheckResponse:
    start = time.perf_counter()
    results = check_notes(body.notes, include_duplicate_ids=include_duplicate_ids)
    return NoteCheckResponse(
        results=results,
        stats={"duration_ms": round((time.perf_counter() - start) * 1000, 3)},
    )


@router.post(
    "/v1/notes",
    response_model=NoteCreateResponse,
    response_model_exclude_none=True,
    summary="Create one or more notes",
    description=(
        "Accepts one note object or an array. Always returns created and failed arrays, "
        "with zero-based input indexes (0 for a single object). Valid notes stay saved "
        "when another note is rejected. Inputs are processed in order and successful additions "
        "form one undo step. Malformed request bodies return 422 before writes. "
        "Add include=cards to return generated card IDs. Upload media separately and reference "
        "the stored filenames in fields."
    ),
    tags=["Notes"],
    operation_id="createNotes",
)
@handle_mutation_errors("create notes")
def create(
    body: Union[List[NoteCreate], NoteCreate] = Body(..., description="One note or an array of notes"),
    include: Optional[Literal["cards"]] = Query(default=None, description="Also return generated card IDs"),
) -> NoteCreateResponse:
    return create_notes(body if isinstance(body, list) else [body], include_cards=include == "cards")
