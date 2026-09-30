import time
from typing import List, Literal, Optional, Union

from fastapi import Body, Header, Query
from fastapi.responses import JSONResponse

from ...adapters import idempotency
from ...adapters.anki.note_batches import create_notes, upsert_notes
from ...adapters.anki.notes import (
    NOTE_SQL,
    check_notes,
    delete_notes,
    find_note_ids,
    get_notes_by_first_fields,
    get_notes_by_ids,
    page_note_ids,
    patch_note,
)
from ...adapters.anki.sorting import find_sorted, sort_names
from ...adapters.ops import collection_op_run_async
from ...shared.errors import ValidationError, handle_mutation_errors
from ...shared.permissions import requires
from ...shared.planning import (
    IndexSpec,
    MutationCaps,
    OrderSpec,
    SearchSpec,
    SourceCaps,
)
from ...shared.route_factory import ModelRow, create_resource_routes, make_id_getter
from ...shared.schemas.creation import IDEMPOTENCY_HELP
from ...shared.schemas.media import sanitize_media_filename
from ...shared.schemas.notes import (
    NoteCheckRequest,
    NoteCheckResponse,
    NoteCreate,
    NoteCreateResponse,
    NoteUpsert,
    NoteUpsertResponse,
)
from ...shared.schemas.wrappers import Paginated
from .media import resolve_upload

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
        # Anki's first-field checksum index: "notes for these words" without
        # reading every note.
        IndexSpec(
            path=("first_field",),
            fetch_values=get_notes_by_first_fields,
            coerce=lambda v: v if isinstance(v, str) else None
        ),
    ],
    # No columns_fetchers: no backend route returns a cheaper subset of a note.
    # page_ids: bare and where-filtered listings walk the notes primary key
    # keyset-style instead of materializing every note id per page request.
    # A `search=` query still enumerates in full - Anki search has no keyset.
    search=SearchSpec(find_ids=find_note_ids, hydrate=get_notes_by_ids,
                      page_ids=page_note_ids, id_field="id"),
    # where clauses on note columns, and first_field by checksum, go into the
    # id query, with or without a search (backlog 9.13).
    sql=NOTE_SQL,
    # order= uses Anki's Browser sorts, in notes mode (backlog 8.1).
    order=OrderSpec(names=lambda: sort_names(True),
                    ordered_ids=lambda query, name, desc: find_sorted(query, name, desc, True)),
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
    permission_resource="notes",
    tag="Notes",
    description="Notes hold the content; cards are generated from them by a model's templates. Use `search` for Anki query syntax."
)


@router.post(
    "/v1/notes:check",
    openapi_extra=requires("read:notes"),
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
) -> dict:
    start = time.perf_counter()
    results = check_notes(body.notes, include_duplicate_ids=include_duplicate_ids)
    # Keep response validation in FastAPI instead of building these models twice.
    return {
        "results": results,
        "stats": {"duration_ms": round((time.perf_counter() - start) * 1000, 3)},
    }


@router.post(
    "/v1/notes:upsert",
    openapi_extra=requires("write:notes"),
    response_model=NoteUpsertResponse,
    response_model_exclude_none=True,
    summary="Create notes, or update the notes they match",
    description=(
        "Accepts one note object or an array, like POST /v1/notes. Each note is matched "
        "against existing notes of its note type: by default with Anki's duplicate check (the "
        "first field, HTML ignored, honoring duplicateScope), or by `match.field`'s exact "
        "content. No match: the note is created (duplicate rules apply). One match: that note "
        "is updated by `on_match`, and its cards stay in their decks. Several matches: the item "
        "fails as `ambiguous` with the note ids. Fields the request does not send are never "
        "touched; a field without a rule is filled only if empty. Returns created, updated "
        "(with the fields that changed) and failed; successful writes form one undo step."
    ),
    tags=["Notes"],
    operation_id="upsertNotes",
)
@handle_mutation_errors("upsert notes")
def upsert(
    body: Union[List[NoteUpsert], NoteUpsert] = Body(..., description="One note or an array of notes"),
    include: Optional[Literal["cards"]] = Query(default=None, description="Also return card IDs"),
) -> NoteUpsertResponse:
    return upsert_notes(body if isinstance(body, list) else [body], include_cards=include == "cards")


def _fetch_attachments(candidates: List[NoteCreate]) -> dict:
    """Each note's files, fetched here on the request thread (downloads stay
    outside the collection operation); a note whose file can't be fetched
    fails alone."""
    attachments, errors = {}, {}
    for index, req in enumerate(candidates):
        try:
            files = []
            for kind, attachment in req.attachments():
                name, data = resolve_upload(attachment)
                sanitize_media_filename(name)   # a bad name fails before anything is stored
                files.append((kind, name, data, list(attachment.fields)))
            if files:
                attachments[index] = files
        except ValidationError as exc:
            errors[index] = str(exc)
    return {"attachments": attachments, "attachment_errors": errors}


@router.post(
    "/v1/notes",
    openapi_extra=requires("write:notes"),
    response_model=NoteCreateResponse,
    response_model_exclude_none=True,
    summary="Create one or more notes",
    description=(
        "Accepts one note object or an array. Always returns created and failed arrays, "
        "with zero-based input indexes (0 for a single object). Valid notes stay saved "
        "when another note is rejected. Inputs are processed in order and successful additions "
        "form one undo step. Malformed request bodies return 422 before writes. "
        "Add include=cards to return generated card IDs, and include_duplicate_ids=true for "
        "the existing notes each duplicate matches (as POST /v1/notes:check reports them). Files can come with each note in "
        "audio, video and picture, as in AnkiConnect: each is stored once its note passes its "
        "checks, and its reference is appended to the listed fields. For many or large files, "
        "or one file shared by several notes, upload them to /v1/media first instead."
    ),
    tags=["Notes"],
    operation_id="createNotes",
)
@handle_mutation_errors("create notes")
def create(
    body: Union[List[NoteCreate], NoteCreate] = Body(..., description="One note or an array of notes"),
    include: Optional[Literal["cards"]] = Query(default=None, description="Also return generated card IDs"),
    include_duplicate_ids: bool = Query(default=False,
                                        description="For duplicates, also look up the notes they match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", description=IDEMPOTENCY_HELP),
) -> Union[NoteCreateResponse, JSONResponse]:
    candidates = body if isinstance(body, list) else [body]
    include_cards = include == "cards"
    if not idempotency_key:
        return create_notes(candidates, include_cards=include_cards, include_duplicate_ids=include_duplicate_ids,
                            **_fetch_attachments(candidates))

    def start(done, fail):
        # Recorded when the write completes, even after this request's 503.
        collection_op_run_async(create_notes.__wrapped__, candidates, include_cards=include_cards,
                                include_duplicate_ids=include_duplicate_ids,
                                **_fetch_attachments(candidates),
                                on_success=lambda r: done(r.dict(exclude_none=True)), on_failure=fail)
    response, replayed = idempotency.run(
        idempotency.scope("POST /v1/notes", idempotency_key),
        idempotency.fingerprint([c.dict() for c in candidates], include_cards, include_duplicate_ids), start)
    return JSONResponse(response, headers={"Idempotent-Replayed": "true"} if replayed else None)
