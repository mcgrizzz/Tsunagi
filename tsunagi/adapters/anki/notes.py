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
def find_card_ids(col: Collection, query: str) -> List[int]:
    """Anki search -> card ids (guiBrowse's return value)."""
    try:
        return [int(i) for i in col.find_cards(query)]
    except Exception as e:
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


# ====================
# AnkiConnect-shaped entry points
#
# These exist so the compat layer is a translation over the same internals
# the native API uses, rather than a second path into Anki. They carry
# AnkiConnect's quirks (case-insensitive field names, scoped duplicate
# checks, media-before-dedup) which the native API deliberately does not.
# ====================

def _ac_options(options: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a note spec's `options`, reproducing canonical's strict bool checks
    (`1` is rejected, not coerced) and its exact messages.
    """
    from ...http.compat.errors import (
        OPTION_ALLOW_DUPLICATE_BOOL,
        OPTION_CHECK_ALL_MODELS_BOOL,
        OPTION_CHECK_CHILDREN_BOOL,
    )

    out = {"allow_duplicate": False, "scope": None, "scope_deck": None,
           "check_children": False, "check_all_models": False}
    if "allowDuplicate" in options:
        if not isinstance(options["allowDuplicate"], bool):
            raise ValueError(OPTION_ALLOW_DUPLICATE_BOOL)
        out["allow_duplicate"] = options["allowDuplicate"]
    if "duplicateScope" in options:
        out["scope"] = options["duplicateScope"]  # not type-validated by canonical
    dso = options.get("duplicateScopeOptions") or {}
    if "deckName" in dso:
        out["scope_deck"] = dso["deckName"]
    if "checkChildren" in dso:
        if not isinstance(dso["checkChildren"], bool):
            raise ValueError(OPTION_CHECK_CHILDREN_BOOL)
        out["check_children"] = dso["checkChildren"]
    if "checkAllModels" in dso:
        if not isinstance(dso["checkAllModels"], bool):
            raise ValueError(OPTION_CHECK_ALL_MODELS_BOOL)
        out["check_all_models"] = dso["checkAllModels"]
    return out


def _ac_apply_fields(note: Any, fields: Dict[str, str]) -> None:
    """Case-insensitive, first match wins, unknown names silently dropped."""
    lowered = {name.lower(): name for name in note.keys()}
    for name, value in fields.items():
        target = lowered.get(name.lower())
        if target is not None:
            note[target] = value


def _ac_duplicate_state(col: Collection, note: Any, deck: Dict[str, Any],
                        opts: Dict[str, Any]) -> int:
    """
    AnkiConnect's isNoteDuplicateOrEmptyInScope: 1 empty, 2 duplicate, 0 ok.

    The default branch delegates to Anki (matching canonical's use of
    dupeOrEmpty), so cloze/HTML handling comes along for free. The manual
    branch is a literal port with deliberately different semantics clients
    depend on: raw .strip() emptiness with no HTML stripping, and csum-only
    matching with no exact-text comparison.
    """
    from anki.utils import field_checksum

    if opts["scope"] != "deck" and not opts["check_all_models"]:
        state = fields_check_impl(col, note)
        return state if state in (EMPTY, DUPLICATE) else NORMAL

    val = note.fields[0] if note.fields else ""
    if not val.strip():
        return EMPTY
    csum = field_checksum(val)

    dids = None
    if opts["scope"] == "deck":
        did = int(deck["id"])
        if opts["scope_deck"] is not None:
            other = col.decks.by_name(opts["scope_deck"])
            if other is None:
                return NORMAL  # invalid deck, so it cannot be a duplicate
            did = int(other["id"])
        dids = {did}
        if opts["check_children"]:
            for _name, child_id in col.decks.children(did):
                dids.add(int(child_id))

    query = "select id from notes where csum = ?"
    args: List[Any] = [csum]
    if note.id:
        query += " and id != ?"
        args.append(note.id)
    if not opts["check_all_models"]:
        query += " and mid = ?"
        args.append(note.mid)

    for nid in col.db.list(query, *args):
        if dids is None:
            return DUPLICATE
        for did2 in col.db.list("select did from cards where nid = ?", nid):
            if int(did2) in dids:
                return DUPLICATE
    return NORMAL


def _ac_prepare(col: Collection, deck_name: str, model_name: str,
                fields: Dict[str, str], tags: Sequence[str], options: Dict[str, Any]):
    """Shared front half of createNote: resolve, fill, and check."""
    from ...http.compat.errors import DECK_NOT_FOUND, MODEL_NOT_FOUND

    model = col.models.by_name(model_name)
    if model is None:
        raise ValueError(MODEL_NOT_FOUND.format(model_name))
    deck = col.decks.by_name(deck_name)
    if deck is None:
        raise ValueError(DECK_NOT_FOUND.format(deck_name))

    opts = _ac_options(options or {})
    note = col.new_note(model)
    _ac_apply_fields(note, fields)
    note.tags = list(tags or [])
    return note, model, deck, opts


def _ac_finish_check(col: Collection, note: Any, deck: Dict[str, Any],
                     opts: Dict[str, Any]) -> None:
    from ...http.compat.errors import NOTE_DUPLICATE, NOTE_EMPTY

    state = _ac_duplicate_state(col, note, deck, opts)
    if state == EMPTY:
        raise ValueError(NOTE_EMPTY)
    if state == DUPLICATE and not opts["allow_duplicate"]:
        raise ValueError(NOTE_DUPLICATE)


def _ac_write_media(col: Collection, note: Any, media: Sequence[Dict[str, Any]]) -> None:
    """
    Store attachments and append their markup. Runs before the duplicate
    check (canonical order), so markup in the first field affects dedup.
    """
    for item in media:
        if item.get("error"):
            for field in item.get("fields") or []:
                if field in note:
                    note[field] += item["error"]
            continue
        data = item.get("data")
        if data is None:
            continue  # skipHash matched: store nothing, append nothing
        if item.get("delete_existing"):
            col.media.trash_files([item["filename"]])
        stored = col.media.write_data(item["filename"], data)
        for field in item.get("fields") or []:
            if field in note:
                note[field] += item["markup"].format(stored)


@as_collection_op
def ac_add_note(col: Collection, deck_name: str, model_name: str,
                fields: Dict[str, str], tags: Sequence[str],
                options: Dict[str, Any], media: Sequence[Dict[str, Any]]) -> int:
    from ...http.compat.errors import EMPTY_QUESTION

    note, _model, deck, opts = _ac_prepare(col, deck_name, model_name, fields, tags, options)
    _ac_write_media(col, note, media)
    _ac_finish_check(col, note, deck, opts)

    res = col.add_note(note, int(deck["id"]))
    if int(getattr(res, "count", 1) or 0) < 1:
        raise ValueError(EMPTY_QUESTION)
    return int(note.id)


@as_query_op
def ac_check_note(col: Collection, deck_name: str, model_name: str,
                  fields: Dict[str, str], options: Dict[str, Any]) -> bool:
    """Probe for canAddNotes: raises the canonical string, never writes."""
    note, _model, deck, opts = _ac_prepare(col, deck_name, model_name, fields, [], options)
    _ac_finish_check(col, note, deck, opts)
    return True


@as_collection_op
def ac_update_note_fields(col: Collection, note_id: int, fields: Dict[str, str],
                          media: Sequence[Dict[str, Any]]) -> None:
    from ...http.compat.errors import NOTE_NOT_FOUND

    try:
        note = col.get_note(int(note_id))
    except Exception as e:
        if type(e).__name__ == "NotFoundError":
            raise ValueError(NOTE_NOT_FOUND.format(note_id)) from e
        raise

    # Exact-case here, unlike createNote. Canonical asymmetry.
    for name, value in fields.items():
        if name in note:
            note[name] = value
    _ac_write_media(col, note, media)
    col.update_note(note)


def profile_name() -> str:
    """Current profile name (notesInfo reports it)."""
    try:
        from aqt import mw
        return mw.pm.name
    except Exception:
        return ""
