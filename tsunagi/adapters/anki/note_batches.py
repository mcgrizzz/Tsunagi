"""Native note batches: shared setup, independent validation, one undo step."""
from typing import Any, Dict, List, Optional, Tuple

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
    NoteUpdated,
    NoteUpsert,
    NoteUpsertResponse,
)
from ..ops import ValueWithChanges, as_collection_op
from .media import write_media
from .notes import (
    EMPTY,
    _apply_fields,
    _duplicate_ids,
    _duplicate_state,
    _fields_to_map,
    _prepare_note,
    _resolve_deck_id,
    _resolve_notetype,
)

# A note's attachment, fetched on the request thread: (kind, filename, bytes, fields).
Attachment = Tuple[str, str, bytes, List[str]]
_MARKUP = {"audio": "[sound:{}]", "video": "[sound:{}]", "picture": '<img src="{}">'}


def _with_references(values: Dict[str, str], files: List[Attachment]) -> Dict[str, str]:
    """Field values with each file's reference appended to its fields, as AnkiConnect does."""
    out = dict(values)
    for kind, name, _data, fields in files:
        for field in fields:
            out[field] = out.get(field, "") + _MARKUP[kind].format(name)
    return out


def _store_attachments(col: Collection, note: Any, files: List[Attachment]) -> None:
    """Store a checked note's files; a renamed file's references follow it."""
    for kind, name, data, fields in files:
        stored, _renamed = write_media(col, name, data)
        if stored != name:
            old, new = _MARKUP[kind].format(name), _MARKUP[kind].format(stored)
            for field in fields:
                note[field] = note[field].replace(old, new)


@as_collection_op
def create_notes(col: Collection, candidates: List[NoteCreate], *,
                 include_cards: bool = False,
                 attachments: Optional[Dict[int, List[Attachment]]] = None,
                 attachment_errors: Optional[Dict[int, str]] = None) -> NoteCreateResponse:
    """attachments/attachment_errors: by input index, fetched before this
    operation (downloads stay outside it). A note's files are stored only once
    the note has passed its checks, so a rejected note leaves no files."""
    attachments, attachment_errors = attachments or {}, attachment_errors or {}
    created: List[NoteCreated] = []
    failed: List[CreationFailure] = []
    # These lookups live only inside this serialized collection operation.
    models, decks = {}, {}
    target = None
    changes = OpChanges()
    for index, req in enumerate(candidates):
        if index in attachment_errors:
            failed.append(CreationFailure(index=index, code="invalid_attachment",
                                          message=attachment_errors[index]))
            continue
        files = attachments.get(index, [])
        try:
            model_key = (req.model_id, req.model_name)
            if model_key not in models:
                models[model_key] = _resolve_notetype(col, req)
            deck_key = (req.deck_id, req.deck_name)
            if deck_key not in decks:
                decks[deck_key] = _resolve_deck_id(col, req)
            # Validate immediately before adding: earlier successes in this
            # batch must participate in duplicate checks too.
            note = _prepare_note(col, req, models[model_key], decks[deck_key],
                                 include_duplicate_ids=False,
                                 field_values=_with_references(_fields_to_map(req.fields), files)
                                 if files else None)
            _store_attachments(col, note, files)
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


# ====================
# Upsert (backlog 7.1)
# ====================

def _matches(col: Collection, req: NoteUpsert, note: Any, nt: Dict[str, Any], deck_id: int) -> List[int]:
    """Existing notes this item identifies. Default: Anki's duplicate check
    (first field, HTML ignored) with the request's duplicate scope; with
    match.field, that field's exact content (case-insensitive) in the note type."""
    from anki.collection import SearchNode

    name = req.match.field
    if name is None:
        state, scoped = _duplicate_state(col, note, req, deck_id)
        if state == EMPTY:
            raise ValidationError("first field is empty")
        return scoped if scoped is not None else _duplicate_ids(col, note)
    if name not in note.keys():
        raise ValidationError(f"Unknown match field '{name}' for model '{nt['name']}'")
    if not note[name]:
        raise ValidationError(f"match field '{name}' is empty")
    query = col.build_search_string(
        SearchNode(note=nt["name"]),
        SearchNode(field=SearchNode.Field(field_name=name, text=note[name])))
    return [int(i) for i in col.find_notes(query)]


def _merge(existing: str, new: str, rule: str, separator: str) -> str:
    if rule == "keep" or not new:
        return existing
    if rule == "replace":
        return new
    if rule == "replace_if_empty":
        return existing or new
    # append: skip a value already there, so repeating an upsert adds nothing
    if not existing or new == existing:
        return new if not existing else existing
    return existing if new in existing.split(separator) else existing + separator + new


def _merge_into(target: Any, req: NoteUpsert) -> Tuple[List[str], bool]:
    """Apply on_match to the existing note in memory; (fields changed, tags changed)."""
    rules, sent = req.on_match.fields, _fields_to_map(req.fields)
    unknown = sorted(set(sent) - set(target.keys()))
    if unknown:
        raise ValidationError(f"Unknown field(s) for this note: {unknown}")
    changed = []
    for name, value in sent.items():
        rule = rules.get(name, rules.get("*", "replace_if_empty"))
        merged = _merge(target[name], value, rule, req.on_match.separator)
        if merged != target[name]:
            target[name] = merged
            changed.append(name)
    before = sorted(target.tags)
    if req.on_match.tags == "replace":
        target.tags = list(req.tags)
    elif req.on_match.tags == "union":
        target.tags = target.tags + [t for t in req.tags if t not in target.tags]
    return changed, sorted(target.tags) != before


@as_collection_op
def upsert_notes(col: Collection, candidates: List[NoteUpsert], *,
                 include_cards: bool = False) -> NoteUpsertResponse:
    """Create each note, or merge it into the one existing note it matches.
    Successful writes form one undo step, as in create_notes."""
    out = NoteUpsertResponse()
    models, decks = {}, {}
    target_step, changes = None, OpChanges()

    def record(step: Any) -> None:
        nonlocal target_step, changes
        if target_step is None:
            target_step, changes = col.undo_status().last_step, step
        else:
            changes = col.merge_undo_entries(target_step)

    for index, req in enumerate(candidates):
        if req.attachments():
            out.failed.append(CreationFailure(
                index=index, code="invalid_note",
                message="upsert doesn't take attachments; upload them with POST /v1/media "
                        "and put their names in the fields"))
            continue
        try:
            model_key, deck_key = (req.model_id, req.model_name), (req.deck_id, req.deck_name)
            if model_key not in models:
                models[model_key] = _resolve_notetype(col, req)
            if deck_key not in decks:
                decks[deck_key] = _resolve_deck_id(col, req)
            nt, deck_id = models[model_key], decks[deck_key]
            probe = col.new_note(nt)
            _apply_fields(probe, _fields_to_map(req.fields), nt["name"])
            found = _matches(col, req, probe, nt, deck_id)
            if len(found) > 1:
                out.failed.append(CreationFailure(
                    index=index, code="ambiguous",
                    message=f"Matches {len(found)} notes: {', '.join(map(str, sorted(found)))}"))
                continue
            if not found:
                note = _prepare_note(col, req, nt, deck_id, include_duplicate_ids=False)
                record(col.add_note(note, deck_id))
                out.created.append(NoteCreated(
                    index=index, id=int(note.id),
                    cards=list(col.card_ids_of_note(note.id)) if include_cards else None))
                continue
            note = col.get_note(found[0])
            fields_changed, tags_changed = _merge_into(note, req)
            if fields_changed or tags_changed:
                record(col.update_note(note))
            out.updated.append(NoteUpdated(
                index=index, id=int(note.id), fields_changed=fields_changed, tags_changed=tags_changed,
                cards=list(col.card_ids_of_note(note.id)) if include_cards else None))
        except DuplicateNoteError:
            out.failed.append(CreationFailure(index=index, code="duplicate",
                                              message="Note duplicates an existing note"))
        except ValidationError as exc:
            out.failed.append(CreationFailure(index=index, code="invalid_note", message=str(exc)))
        except Exception as exc:
            if type(exc).__name__ not in ANKI_CLIENT_ERRORS:
                raise
            out.failed.append(CreationFailure(index=index, code="anki_error",
                                              message=anki_error_detail(exc)))

    return ValueWithChanges(out, changes, event_changes=lambda: {"notes": {
        "created": [n.id for n in out.created],
        "updated": [n.id for n in out.updated if n.fields_changed or n.tags_changed]}})
