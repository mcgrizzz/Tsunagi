"""Native note batches: shared setup, independent validation, one undo step."""
from typing import List

from anki.collection import Collection, OpChanges

from ...shared.errors import (
    ANKI_CLIENT_ERRORS,
    DuplicateNoteError,
    ValidationError,
    anki_error_detail,
)
from ...shared.schemas.creation import CreationFailure
from ...shared.schemas.notes import (
    NoteCreate,
    NoteCreated,
    NoteCreateResponse,
)
from ..ops import ValueWithChanges, as_collection_op
from .notes import _prepare_note, _resolve_deck_id, _resolve_notetype


@as_collection_op
def create_notes(col: Collection, candidates: List[NoteCreate], *,
                 include_cards: bool = False) -> NoteCreateResponse:
    created: List[NoteCreated] = []
    failed: List[CreationFailure] = []
    # These lookups live only inside this serialized collection operation.
    models, decks = {}, {}
    target = None
    changes = OpChanges()
    for index, req in enumerate(candidates):
        try:
            model_key = (req.model_id, req.model_name)
            if model_key not in models:
                models[model_key] = _resolve_notetype(col, req)
            deck_key = (req.deck_id, req.deck_name)
            if deck_key not in decks:
                decks[deck_key] = _resolve_deck_id(col, req)
            # Validate immediately before adding: earlier successes in this
            # batch must participate in duplicate checks too.
            note = _prepare_note(col, req, models[model_key], include_duplicate_ids=False)
            step = col.add_note(note, decks[deck_key])
        except DuplicateNoteError:
            failed.append(CreationFailure(index=index, code="duplicate",
                                            message="Note duplicates an existing note"))
            continue
        except ValidationError as exc:
            failed.append(CreationFailure(index=index, code="invalid_note", message=str(exc)))
            continue
        except Exception as exc:
            if type(exc).__name__ not in ANKI_CLIENT_ERRORS:
                raise
            failed.append(CreationFailure(index=index, code="anki_error",
                                            message=anki_error_detail(exc)))
            continue

        if target is None:
            # Anchor to the first successful write, so all-invalid/empty
            # requests do not create an empty undo entry.
            target = col.undo_status().last_step
            changes = step
        else:
            # Merge after each write, before Anki's bounded undo history can
            # discard the first step. The returned flags cover the whole batch.
            changes = col.merge_undo_entries(target)
        created.append(NoteCreated(index=index, id=int(note.id),
                                   cards=list(col.card_ids_of_note(note.id)) if include_cards else None))

    result = NoteCreateResponse(created=created, failed=failed)
    return ValueWithChanges(result, changes, event_changes=lambda: {
        "notes": {"created": [note.id for note in created]},
        # The operation runner evaluates this only for active change listeners.
        # Card IDs are event details, not work every batch response must pay for.
        "cards": {"created": [cid for note in created for cid in (note.cards if note.cards is not None else col.card_ids_of_note(note.id))]},
    })
