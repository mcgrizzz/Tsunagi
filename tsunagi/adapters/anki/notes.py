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
from ..ops import ValueWithChanges, as_collection_op, as_query_op

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
               wants: Optional[Set[str]] = None,
               cards_by_nid: Optional[Dict[int, List[int]]] = None) -> NoteInfo:
    names = list(note.keys())
    fields = [{"name": n, "value": v, "ord": i}
              for i, (n, v) in enumerate(zip(names, note.fields))]
    # A backend call per note unless the page prefetched the map, and only
    # when the caller asked for the field at all.
    cards = None
    if wants is None or "cards" in wants:
        if cards_by_nid is not None:
            cards = cards_by_nid.get(int(note.id), [])
        else:
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
def page_note_ids(col: Collection, after_id: Optional[int], limit: int) -> List[int]:
    """
    The next `limit` note ids after `after_id` (None = from the start),
    ascending. `notes.id` is the primary key (unchanged across every Anki
    schema migration), so this is a pure index walk - the keyset page for a
    bare GET /v1/notes.
    """
    if after_id is None:
        return [int(i) for i in col.db.list(
            "select id from notes order by id limit ?", int(limit))]
    return [int(i) for i in col.db.list(
        "select id from notes where id > ? order by id limit ?",
        int(after_id), int(limit))]


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
    ints = [int(i) for i in ids]
    # One query for the whole page's card ids instead of a backend call per
    # note (ids are ints we produced; `order by nid, ord` matches
    # card_ids_of_note's per-note ordering).
    cards_by_nid: Optional[Dict[int, List[int]]] = None
    if ints and (wants is None or "cards" in wants):
        cards_by_nid = {}
        in_list = ",".join(str(i) for i in ints)
        for cid, nid in col.db.all(
                f"select id, nid from cards where nid in ({in_list})"
                " order by nid, ord"):
            cards_by_nid.setdefault(int(nid), []).append(int(cid))
    out: List[NoteInfo] = []
    for nid in ints:
        try:
            note = col.get_note(nid)
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                continue  # missing ids are skipped, like get_models_by_ids
            raise
        out.append(_note_info(col, note, model_names, wants, cards_by_nid))
    return out


@as_query_op
def check_notes(col: Collection, candidates: List[Dict[str, Any]]) -> List[NoteCheckResult]:
    """
    Can these notes be added? Builds scratch notes that are never added, so
    this is a read - no undo entry, no collection mutation.
    """
    results: List[NoteCheckResult] = []
    # A bulk check usually repeats one model/deck pair; resolve each distinct
    # reference once instead of two backend lookups per candidate.
    nt_cache: Dict[Any, Dict[str, Any]] = {}
    deck_cache: Dict[Any, int] = {}
    for index, data in enumerate(candidates):
        try:
            req = NoteCreate.parse_obj(data)
            nt_key = (req.model_id, req.model_name)
            nt = nt_cache.get(nt_key)
            if nt is None:
                nt = nt_cache[nt_key] = _resolve_notetype(col, req)
            deck_key = (req.deck_id, req.deck_name)
            if deck_key not in deck_cache:
                deck_cache[deck_key] = _resolve_deck_id(col, req)
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

    changes = col.add_note(note, deck_id)
    return ValueWithChanges(
        _note_info(col, note, {int(nt["id"]): nt["name"]}), changes)


def _change_notetype(col: Collection, note: Any, req: NotePatch) -> None:
    """
    Retype a note in place.

    Rebinding `mid` resizes the note to the new notetype's field count, which
    blanks every value - so `fields` is required alongside, or the change would
    silently empty the note. Refreshing the private `_fmap` is what makes
    name-based assignment work afterwards; it is how Anki's own Note builds it,
    and how AnkiConnect's updateNoteModel does the same job.
    """
    if req.fields is None:
        raise ValidationError(
            "changing a note's model requires 'fields': the new model's fields "
            "start empty, so omitting them would erase the note"
        )

    if req.model_id is not None:
        notetype = col.models.get(int(req.model_id))
        missing: Any = req.model_id
    else:
        notetype = col.models.by_name(str(req.model_name))
        missing = req.model_name
    if not notetype:
        raise ValidationError(f"model was not found: {missing}")

    note.mid = int(notetype["id"])
    note._fmap = col.models.field_map(notetype)
    note.fields = [""] * len(notetype["flds"])


@as_collection_op(event_details=lambda note_id, updates: {"note_ids": [int(note_id)]})
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

    if req.model_id is not None or req.model_name is not None:
        _change_notetype(col, note, req)

    model_names = _model_names(col)
    if req.fields is not None:
        _apply_fields(note, _fields_to_map(req.fields),
                      model_names.get(int(note.mid), ""))

    if req.tags is not None:
        note.tags = list(req.tags)
    if req.add_tags:
        note.tags = list(note.tags) + [t for t in req.add_tags if t not in note.tags]
    if req.remove_tags:
        drop = set(req.remove_tags)
        note.tags = [t for t in note.tags if t not in drop]

    changes = col.update_note(note)
    return ValueWithChanges(_note_info(col, note, model_names), changes)


@as_collection_op(event_details=lambda ids: {"note_ids": [int(i) for i in ids]})
def delete_notes(col: Collection, ids: Sequence[int]) -> int:
    """Batch by design: one undoable op. Compat's deleteNotes reuses this."""
    res = col.remove_notes([int(i) for i in ids])
    return ValueWithChanges(int(getattr(res, "count", 0) or 0), res)


# ====================
# AnkiConnect-shaped entry points
#
# These exist so the compat layer is a translation over the same internals
# the native API uses, rather than a second path into Anki. They carry
# AnkiConnect's quirks (case-insensitive field names, scoped duplicate
# checks, media-before-dedup) which the native API deliberately does not.
# ====================

def _ac_options(options: Any) -> Dict[str, Any]:
    """
    Parse a note spec's `options`, reproducing canonical's strict bool checks
    (`1` is rejected, not coerced) and its exact messages.
    """
    from ...http.compat.errors import (
        OPTION_ALLOW_DUPLICATE_BOOL,
        OPTION_CHECK_ALL_MODELS_BOOL,
        OPTION_CHECK_CHILDREN_BOOL,
    )

    try:
        out = {"allow_duplicate": False, "scope": None, "scope_deck": None,
               "check_children": False, "check_all_models": False}
        if "allowDuplicate" in options:
            if not isinstance(options["allowDuplicate"], bool):
                raise ValueError(OPTION_ALLOW_DUPLICATE_BOOL)
            out["allow_duplicate"] = options["allowDuplicate"]
        if "duplicateScope" in options:
            out["scope"] = options["duplicateScope"]  # not type-validated by canonical
        dso = options["duplicateScopeOptions"] if "duplicateScopeOptions" in options else {}
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
    except Exception as exc:
        raise ValueError(str(exc)) from exc


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
        return fields_check_impl(col, note) or NORMAL

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


def _ac_prepare(col: Collection, spec):
    """Resolve and fill raw note input in AnkiConnect's validation order."""
    from ...http.compat.errors import DECK_NOT_FOUND, MODEL_NOT_FOUND

    model_name = spec["modelName"]
    model = col.models.by_name(model_name)
    if model is None:
        raise ValueError(MODEL_NOT_FOUND.format(model_name))
    deck_name = spec["deckName"]
    deck = col.decks.by_name(deck_name)
    if deck is None:
        raise ValueError(DECK_NOT_FOUND.format(deck_name))

    note = col.new_note(model)
    note.note_type()["did"] = deck["id"]
    note.tags = spec.get("tags", [])
    _ac_apply_fields(note, spec["fields"])
    return note, model, deck, spec.get("options", {})


@as_query_op
def ac_validate_note(col: Collection, spec, *, updating: bool = False) -> None:
    """Check the pre-media input before the request thread fetches attachments.

    The final operation prepares again: collection state can change while a
    download is in flight. No Anki note object crosses the operation boundary.
    """
    try:
        if updating:
            _ac_prepare_update(col, spec["id"], spec.get("fields"),
                               fields_missing="fields" not in spec)
        else:
            _ac_prepare(col, spec)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _ac_finish_check(col: Collection, note: Any, deck: Dict[str, Any],
                     opts: Dict[str, Any]) -> None:
    from ...http.compat.errors import NOTE_DUPLICATE, NOTE_EMPTY

    state = _ac_duplicate_state(col, note, deck, opts)
    if state == EMPTY:
        raise ValueError(NOTE_EMPTY)
    if state == DUPLICATE and not opts["allow_duplicate"]:
        raise ValueError(NOTE_DUPLICATE)
    if state not in (NORMAL, EMPTY, DUPLICATE):
        raise ValueError("cannot create note for unknown reason")


def _ac_store_media(col: Collection, item: Mapping[str, Any]):
    """Return a plain storage outcome; field error handling remains below."""
    from os import fspath

    try:
        if item.get("error") is not None:
            raise ValueError(item["error"])
        data = item.get("data")
        if data is None:
            return None  # skipHash matched
        if item.get("delete_existing") and not isinstance(item["filename"], str):
            # Upstream's deletion protobuf rejects the type before writeData.
            raise TypeError("bad argument type for built-in operation")
        # Preserve legacy filename type errors before invoking the backend.
        filename = fspath(item["filename"])
        if item.get("delete_existing"):
            col.media.trash_files([filename])
        stored = col.media.write_data(filename, data)
        return {"filename": stored}
    except Exception as exc:
        return {"error": str(exc)}


def _ac_write_media(col: Collection, note: Any, media: Sequence[Dict[str, Any]]) -> None:
    """
    Store attachments and append their markup. Runs before the duplicate
    check (canonical order), so markup in the first field affects dedup.
    """
    for item in media:
        if "abort_error" in item:
            raise ValueError(item["abort_error"])
        try:
            outcome = item["_storage_result"] if "_storage_result" in item else _ac_store_media(col, item)
            if outcome is None:
                continue
            if "error" in outcome:
                raise ValueError(outcome["error"])
            stored = outcome["filename"]
            fields = item.get("fields")
            if type(fields) is list:
                for field in fields:
                    if field in note:
                        note[field] += item["markup"].format(stored)
        except Exception as error:
            message = str(error).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            try:
                # Upstream does not guard this path by type or key presence.
                # A missing/noniterable selection aborts the enclosing action.
                for field in item["fields"]:
                    if field in note:
                        note[field] += message
            except Exception as exc:
                raise ValueError(str(exc)) from exc


@as_collection_op
def ac_stage_note_media(col: Collection, spec, item: Dict[str, Any],
                        field_values: Optional[Dict[str, Any]] = None, *, updating: bool = False):
    """Store one attachment and check continuation before the next download.

    Only plain field values and storage outcomes cross operation boundaries.
    The final note operation replays the outcomes against a freshly read note.
    """
    from anki.collection import OpChanges

    try:
        if updating:
            note = _ac_prepare_update(col, spec["id"], spec.get("fields"),
                                      fields_missing="fields" not in spec)
        else:
            note, _model, _deck, _options = _ac_prepare(col, spec)
        if field_values is not None:
            for name, value in field_values.items():
                if name in note:
                    note[name] = value
        staged = dict(item)
        if "abort_error" not in staged:
            staged["_storage_result"] = _ac_store_media(col, staged)
            staged.pop("data", None)  # release downloaded bytes after storage
        _ac_write_media(col, note, [staged])
        return ValueWithChanges((staged, dict(note.items())), OpChanges())
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def ac_add_note(col: Collection, spec, media: Sequence[Dict[str, Any]] = ()) -> int:
    try:
        from ...http.compat.errors import EMPTY_QUESTION

        note, _model, deck, raw_options = _ac_prepare(col, spec)
        _ac_write_media(col, note, media)
        _ac_finish_check(col, note, deck, _ac_options(raw_options))

        res = col.add_note(note, int(deck["id"]))
        if int(getattr(res, "count", 1) or 0) < 1:
            raise ValueError(EMPTY_QUESTION)
        return ValueWithChanges(int(note.id), res)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def ac_check_note(col: Collection, spec, media: Sequence[Dict[str, Any]] = ()) -> bool:
    """Prepare a probe, including upstream media side effects, without adding it."""
    try:
        from anki.collection import OpChanges

        note, _model, deck, raw_options = _ac_prepare(col, spec)
        _ac_write_media(col, note, media)
        _ac_finish_check(col, note, deck, _ac_options(raw_options))
        return ValueWithChanges(True, OpChanges())
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _ac_prepare_update(col: Collection, note_id: Any, fields: Any, *, fields_missing=False):
    """Apply fields to an unsaved note, shared by preflight and the final write."""
    from ...http.compat.errors import NOTE_NOT_FOUND

    try:
        note = col.get_note(note_id)
        if fields_missing:
            raise KeyError("fields")
        # Exact-case here, unlike createNote and updateNoteModel.
        for name, value in fields.items():
            if name in note:
                note[name] = value
        return note
    except Exception as exc:
        if type(exc).__name__ == "NotFoundError":
            raise ValueError(NOTE_NOT_FOUND.format(note_id)) from exc
        raise ValueError(str(exc)) from exc


@as_collection_op
def ac_update_note_fields(col: Collection, note_id: Any, fields: Any,
                          media: Sequence[Dict[str, Any]], *, fields_missing=False) -> None:
    from ...http.compat.errors import NOTE_NOT_FOUND

    try:
        note = _ac_prepare_update(col, note_id, fields, fields_missing=fields_missing)
        _ac_write_media(col, note, media)
        return ValueWithChanges(None, col.update_note(note, skip_undo_entry=True))
    except Exception as exc:
        if type(exc).__name__ == "NotFoundError":
            raise ValueError(NOTE_NOT_FOUND.format(note_id)) from exc
        raise ValueError(str(exc)) from exc


@as_query_op
def notes_mod_times(col: Collection, note_ids: Sequence[int]) -> List[Dict[str, Any]]:
    # One indexed read for the whole batch - the old loop deserialized every
    # note's full field blob to report a single integer per id.
    ints = [int(n) for n in note_ids]
    mods: Dict[int, int] = {}
    if ints:
        for nid, mod in col.db.all(
                "select id, mod from notes where id in ("
                + ",".join(str(i) for i in ints) + ")"):
            mods[int(nid)] = int(mod or 0)
    return [{"noteId": n, "mod": mods.get(n)} for n in ints]


def profile_name() -> str:
    """Current profile name (notesInfo reports it)."""
    try:
        from aqt import mw
        return mw.pm.name
    except Exception:
        return ""
