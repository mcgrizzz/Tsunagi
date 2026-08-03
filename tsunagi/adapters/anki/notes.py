"""
Note reads and mutations.

Reads run off the UI thread via QueryOp; writes go through CollectionOp so
they land in Anki's undo stack. Duplicate/empty detection lives here too
(fields_check_impl) because both the native /v1 check endpoint and the
AnkiConnect compat layer need exactly the same answer.
"""
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from anki.collection import Collection

from ...shared.errors import DuplicateNoteError, ResourceNotFoundError, ValidationError
from ...shared.schemas.notes import (
    NoteCheckResult,
    NoteCreate,
    NoteInfo,
    NotePatch,
)
from ..ops import as_collection_op, as_query_op

# note.fields_check() states (anki.notes.NoteFieldsCheckResult)
NORMAL, EMPTY, DUPLICATE, MISSING_CLOZE = 0, 1, 2, 3

_STATE_NAMES = {
    NORMAL: "normal",
    EMPTY: "empty",
    DUPLICATE: "duplicate",
    MISSING_CLOZE: "missing_cloze",
}


def _fields_to_map(fields: Any) -> Dict[str, str]:
    """Accept {"Front": "犬"} or [{"name": "Front", "value": "犬"}]."""
    if isinstance(fields, Mapping):
        return {str(k): "" if v is None else str(v) for k, v in fields.items()}
    out: Dict[str, str] = {}
    for item in fields or []:
        name = item.name if hasattr(item, "name") else item.get("name")
        value = item.value if hasattr(item, "value") else item.get("value", "")
        if not name:
            raise ValidationError("each field entry requires a 'name'")
        if name in out:
            raise ValidationError(f"duplicate field '{name}' in request")
        out[str(name)] = "" if value is None else str(value)
    return out


def _note_info(col: Collection, note: Any, model_names: Dict[int, str],
               wants: Optional[Set[str]] = None) -> NoteInfo:
    names = list(note.keys())
    fields = [{"name": n, "value": v, "ord": i}
              for i, (n, v) in enumerate(zip(names, note.fields))]
    # One backend call per note, so only when the caller asked for it.
    cards = None
    if wants is None or "cards" in wants:
        cards = [int(c) for c in col.card_ids_of_note(note.id)]
    return NoteInfo(
        id=int(note.id),
        guid=getattr(note, "guid", "") or "",
        mid=int(note.mid),
        model_name=model_names.get(int(note.mid), ""),
        mod=int(getattr(note, "mod", 0) or 0),
        usn=int(getattr(note, "usn", 0) or 0),
        tags=list(note.tags),
        fields=fields,
        cards=cards,
    )


def _model_names(col: Collection) -> Dict[int, str]:
    # One call for the whole page; note.note_type() would be a backend call
    # per note.
    return {int(nt.id): nt.name for nt in col.models.all_names_and_ids()}


def _resolve_notetype(col: Collection, req: NoteCreate) -> Dict[str, Any]:
    if req.model_id is not None:
        nt = col.models.get(int(req.model_id))
        if not nt:
            raise ValidationError(f"Unknown model id {req.model_id}")
        return nt
    if req.model_name:
        nt = col.models.by_name(req.model_name)
        if not nt:
            raise ValidationError(f"Unknown model '{req.model_name}'")
        return nt
    raise ValidationError("one of 'model_id' or 'model_name' is required")


def _resolve_deck_id(col: Collection, req: NoteCreate) -> int:
    if req.deck_id is not None:
        deck = col.decks.get(int(req.deck_id), default=False)
        if not deck:
            raise ValidationError(f"Unknown deck id {req.deck_id}")
        return int(deck["id"])
    if req.deck_name:
        deck = col.decks.by_name(req.deck_name)
        if not deck:
            raise ValidationError(f"Unknown deck '{req.deck_name}'")
        return int(deck["id"])
    raise ValidationError("one of 'deck_id' or 'deck_name' is required")


def _apply_fields(note: Any, values: Dict[str, str], notetype_name: str) -> None:
    known = set(note.keys())
    for name, value in values.items():
        if name not in known:
            raise ValidationError(
                f"Unknown field '{name}' for model '{notetype_name}'. Available: {sorted(known)}"
            )
        note[name] = value


def _duplicate_ids(col: Collection, note: Any) -> List[int]:
    """Note ids sharing this note's first field within its notetype."""
    from anki.collection import SearchNode

    first = note.fields[0] if note.fields else ""
    query = col.build_search_string(
        SearchNode(dupe=SearchNode.Dupe(notetype_id=note.mid, first_field=first))
    )
    return [int(i) for i in col.find_notes(query) if int(i) != int(note.id or 0)]


def fields_check_impl(col: Collection, note: Any) -> int:
    """
    Anki's own duplicate/empty/cloze check. A plain function taking `col` so
    it can be called from inside a CollectionOp - wrapping it as a QueryOp
    and calling it there would nest ops and hang until the op timeout.
    """
    return int(note.fields_check())


# ====================
# Reads
# ====================

@as_query_op
def find_note_ids(col: Collection, query: str) -> List[int]:
    """
    Anki search -> note ids. An empty query means the whole collection
    (Anki's parser maps it to WholeCollection).
    """
    try:
        return [int(i) for i in col.find_notes(query)]
    except Exception as e:
        # A malformed search is a client error; without this every typo'd
        # search string becomes a 500.
        if type(e).__name__ in ("SearchError", "InvalidInput"):
            raise ValueError(f"Invalid Anki search: {e}") from e
        raise


@as_query_op
def get_notes_by_ids(col: Collection, ids: Sequence[int],
                     wants: Optional[Set[str]] = None) -> List[NoteInfo]:
    model_names = _model_names(col)
    out: List[NoteInfo] = []
    for nid in ids:
        try:
            note = col.get_note(int(nid))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                continue  # missing ids are skipped, like get_models_by_ids
            raise
        out.append(_note_info(col, note, model_names, wants))
    return out


@as_query_op
def check_notes(col: Collection, candidates: List[Dict[str, Any]]) -> List[NoteCheckResult]:
    """
    Can these notes be added? Builds scratch notes that are never added, so
    this is a read - no undo entry, no collection mutation.
    """
    results: List[NoteCheckResult] = []
    for index, data in enumerate(candidates):
        try:
            req = NoteCreate.parse_obj(data)
            nt = _resolve_notetype(col, req)
            _resolve_deck_id(col, req)
            note = col.new_note(nt)
            _apply_fields(note, _fields_to_map(req.fields), nt["name"])
            note.tags = list(req.tags)

            state = fields_check_impl(col, note)
            dupes = _duplicate_ids(col, note) if state == DUPLICATE else []
            can_add = state == NORMAL or (state == DUPLICATE and req.allow_duplicate)
            results.append(NoteCheckResult(
                index=index,
                can_add=can_add,
                state=_STATE_NAMES.get(state, "unknown"),
                reason=None if can_add else _STATE_NAMES.get(state, "unknown"),
                duplicate_note_ids=dupes,
            ))
        except ValidationError as ve:
            results.append(NoteCheckResult(
                index=index, can_add=False, state="invalid", reason=str(ve),
            ))
    return results


# ====================
# Mutations
# ====================

@as_collection_op
def create_note(col: Collection, data: Dict[str, Any]) -> NoteInfo:
    req = NoteCreate.parse_obj(data)
    nt = _resolve_notetype(col, req)
    deck_id = _resolve_deck_id(col, req)

    note = col.new_note(nt)
    _apply_fields(note, _fields_to_map(req.fields), nt["name"])
    note.tags = list(req.tags)

    state = fields_check_impl(col, note)
    if state == EMPTY:
        raise ValidationError("first field is empty")
    if state == MISSING_CLOZE:
        raise ValidationError("cloze model requires at least one {{c1::...}} in a field")
    if state == DUPLICATE and not req.allow_duplicate:
        raise DuplicateNoteError(_duplicate_ids(col, note))

    col.add_note(note, deck_id)
    return _note_info(col, note, {int(nt["id"]): nt["name"]})


@as_collection_op
def patch_note(col: Collection, note_id: int, updates: Dict[str, Any]) -> NoteInfo:
    req = NotePatch.parse_obj(updates)
    if req.tags is not None and (req.add_tags or req.remove_tags):
        raise ValidationError("'tags' cannot be combined with 'add_tags'/'remove_tags'")

    try:
        note = col.get_note(int(note_id))
    except Exception as e:
        if type(e).__name__ == "NotFoundError":
            raise ResourceNotFoundError("Note", note_id) from e
        raise

    if req.fields is not None:
        model_name = _model_names(col).get(int(note.mid), "")
        _apply_fields(note, _fields_to_map(req.fields), model_name)

    if req.tags is not None:
        note.tags = list(req.tags)
    if req.add_tags:
        note.tags = list(note.tags) + [t for t in req.add_tags if t not in note.tags]
    if req.remove_tags:
        drop = set(req.remove_tags)
        note.tags = [t for t in note.tags if t not in drop]

    col.update_note(note)
    return _note_info(col, note, _model_names(col))


@as_collection_op
def delete_notes(col: Collection, ids: Sequence[int]) -> int:
    """Batch by design: one undoable op. Compat's deleteNotes reuses this."""
    res = col.remove_notes([int(i) for i in ids])
    return int(getattr(res, "count", 0) or 0)
