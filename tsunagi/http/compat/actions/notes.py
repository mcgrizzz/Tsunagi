"""
AnkiConnect compatibility handlers for note actions.

Wire semantics are quoted from the canonical source (git.sr.ht/~foosoft/
anki-connect). The subtle ones, all load-bearing for real clients:
- createNote assigns fields CASE-INSENSITIVELY, first match wins, unknown
  names dropped; updateNoteFields is exact-case. Asymmetric on purpose.
- Media is attached BEFORE the duplicate check, so markup in the first field
  changes the dedup outcome.
- addNotes is all-or-nothing: any failure rolls back everything created.
- canAddNotesWithErrorDetail returns {"canAdd": true} with NO error key, and
  must always return exactly len(notes) entries without raising - Yomitan's
  "already added" badge substring-matches the duplicate error string.
"""
import base64
import hashlib
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki.compat_only import (
    remove_unused_note_types,
    replace_tag_everywhere,
    replace_tag_on_notes,
)
from ....adapters.anki.notes import (
    ac_add_note,
    ac_check_note,
    ac_update_note_fields,
    delete_notes,
    get_notes_by_ids,
    notes_mod_times,
    patch_note,
    profile_name,
)
from ....adapters.anki.tags import add_tags, all_tags, clear_unused_tags, remove_tags
from ..errors import (
    NOTE_NOT_FOUND,
    NOTE_UPDATE_NO_INPUT,
    NOTES_INFO_NO_INPUT,
    TAGS_MUST_BE_LIST,
)
from ..registry import registry


class NoteSpec(BaseModel):
    class Config:
        smart_union = True

    deckName: str
    modelName: str
    fields: Dict[str, str]
    tags: List[str] = []
    options: Optional[Dict[str, Any]] = None
    audio: Any = None
    video: Any = None
    picture: Any = None


class NoteUpdateSpec(BaseModel):
    class Config:
        smart_union = True

    id: int
    fields: Dict[str, str]
    audio: Any = None
    video: Any = None
    picture: Any = None


class AddNoteParams(BaseModel):
    note: NoteSpec


class AddNotesParams(BaseModel):
    notes: List[NoteSpec]


class UpdateNoteFieldsParams(BaseModel):
    note: NoteUpdateSpec


class NotesInfoParams(BaseModel):
    notes: Optional[List[int]] = None
    query: Optional[str] = None


class FindNotesParams(BaseModel):
    query: Any = None


class DeleteNotesParams(BaseModel):
    notes: List[int]


# ---- media attached to a note spec -------------------------------------

_MARKUP = {"picture": '<img src="{}">', "audio": "[sound:{}]", "video": "[sound:{}]"}


def _as_list(value) -> List[Any]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [m for m in items if m is not None]


def _resolve_media(spec) -> List[Dict[str, Any]]:
    """Resolve attachments on the request thread, outside collection operations.

    Keep raw values and defer errors per attachment: upstream can write earlier
    media before a malformed later entry aborts the enclosing action.
    """
    from ....adapters.settings import settings
    from ..downloads import download_media

    out: List[Dict[str, Any]] = []
    for kind in ("audio", "video", "picture"):
        for media in _as_list(getattr(spec, kind, None)):
            entry: Dict[str, Any] = {
                "kind": kind, "markup": _MARKUP[kind], "data": None, "error": None,
            }
            if not isinstance(media, dict):
                try:
                    # The upstream exception handler indexes this key even when
                    # the attachment itself is not a mapping.
                    media["fields"]
                except Exception as exc:
                    entry["abort_error"] = str(exc)
                out.append(entry)
                continue
            if "fields" in media:
                entry["fields"] = media["fields"]
            try:
                entry["filename"] = media["filename"]
                # Unlike standalone storage, the nested default is falsy.
                entry["delete_existing"] = bool(media.get("deleteExisting"))
                encoded, path, url = media.get("data"), media.get("path"), media.get("url")
                if encoded:
                    data = base64.b64decode(encoded)
                elif path:
                    if not settings.gate_enabled("media_allow_local_path"):
                        raise ValueError("local 'path' uploads are disabled (gates.media_allow_local_path)")
                    with open(path, "rb") as fh:
                        data = fh.read()
                elif url:
                    data = download_media(url)
                else:
                    raise ValueError('You must provide a "data", "path", or "url" field.')
                skip_hash = media.get("skipHash")
                if skip_hash is not None and skip_hash == hashlib.md5(data).hexdigest():
                    data = None
                entry["data"] = data
            except Exception as exc:
                # The adapter handles download and storage errors alike,
                # including upstream's distinct field-selection error path.
                entry["error"] = str(exc)
            out.append(entry)
    return out


# ---- actions -----------------------------------------------------------

@registry.register("addNote", params=AddNoteParams)
def ac_addNote(p: AddNoteParams) -> int:
    spec = p.note
    return ac_add_note(spec.deckName, spec.modelName, spec.fields, spec.tags,
                       spec.options or {}, _resolve_media(spec))


@registry.register("addNotes", params=AddNotesParams)
def ac_addNotes(p: AddNotesParams) -> List[int]:
    created: List[int] = []
    errors: List[str] = []
    for spec in p.notes:
        try:
            created.append(ac_add_note(spec.deckName, spec.modelName, spec.fields,
                                       spec.tags, spec.options or {}, _resolve_media(spec)))
        except Exception as e:
            errors.append(str(e))
    if errors:
        # All-or-nothing: canonical rolls back everything it created.
        if created:
            delete_notes(created)
        raise ValueError(str(errors))
    return created


@registry.register("canAddNotes", params=AddNotesParams)
def ac_canAddNotes(p: AddNotesParams) -> List[bool]:
    return [ok for ok, _err in (_can_add(spec) for spec in p.notes)]


@registry.register("canAddNotesWithErrorDetail", params=AddNotesParams)
def ac_canAddNotesWithErrorDetail(p: AddNotesParams) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for spec in p.notes:
        ok, err = _can_add(spec)
        # Success has NO "error" key
        out.append({"canAdd": True} if ok else {"canAdd": False, "error": err})
    return out


def _can_add(spec: NoteSpec):
    """(can_add, error_string). Never raises - one entry per input note."""
    try:
        # Canonical probes prepare media before duplicate/empty checks, even
        # though they never insert the prepared note into the collection.
        ac_check_note(spec.deckName, spec.modelName, spec.fields, spec.options or {},
                      _resolve_media(spec))
        return True, None
    except Exception as e:
        return False, str(e)


@registry.register("updateNoteFields", params=UpdateNoteFieldsParams)
def ac_updateNoteFields(p: UpdateNoteFieldsParams) -> None:
    spec = p.note
    ac_update_note_fields(spec.id, spec.fields, _resolve_media(spec))
    return None


@registry.register("notesInfo", params=NotesInfoParams)
def ac_notesInfo(p: NotesInfoParams) -> List[Dict[str, Any]]:
    from collections import Counter

    from ....adapters.anki.compat import find_ids

    if p.notes is None and p.query is None:
        raise ValueError(NOTES_INFO_NO_INPUT)
    ids = find_ids(p.query) if p.query is not None else list(p.notes)
    # Upstream appends a note's cards once for each 999-ID SQL batch containing
    # that note. Duplicate IDs inside one batch do not multiply its cards.
    card_repetitions = Counter(
        nid for offset in range(0, len(ids), 999)
        for nid in set(ids[offset:offset + 999])
    )

    # Chunked: a broad query can match the whole collection, and hydrating it
    # in one QueryOp would hit the op timeout (503) where canonical answers
    # slowly. Same unbounded result as canonical, bounded per op.
    found = {}
    for i in range(0, len(ids), 250):
        for n in get_notes_by_ids(ids[i:i + 250]):
            found[int(n.id)] = n
    profile = profile_name()
    out: List[Dict[str, Any]] = []
    for nid in ids:
        info = found.get(int(nid))
        if info is None:
            out.append({})  # missing note is {} - Yomitan relies on this
            continue
        out.append({
            "noteId": info.id,
            "profile": profile,
            "tags": info.tags,
            # Array -> AnkiConnect's map shape
            "fields": {f.name: {"value": f.value, "order": f.ord} for f in info.fields},
            "modelName": info.model_name,
            "mod": info.mod,
            "cards": (info.cards or []) * card_repetitions[nid],
        })
    return out


@registry.register("findNotes", params=FindNotesParams)
def ac_findNotes(p: FindNotesParams) -> List[int]:
    from ....adapters.anki.compat import find_ids

    if p.query is None:
        return []
    return find_ids(p.query)


@registry.register("findCards", params=FindNotesParams)
def ac_findCards(p: FindNotesParams) -> List[int]:
    from ....adapters.anki.compat import find_ids

    if p.query is None:
        return []
    return find_ids(p.query, cards=True)


@registry.register("deleteNotes", params=DeleteNotesParams)
def ac_deleteNotes(p: DeleteNotesParams) -> None:
    delete_notes(p.notes)
    return None


class TagsParams(BaseModel):
    notes: List[int]
    tags: str          # space-separated, per AnkiConnect


class AddTagsParams(TagsParams):
    # Public upstream signature, although omitted from its README examples.
    add: bool = True


@registry.register("addTags", params=AddTagsParams)
def ac_addTags(p: AddTagsParams) -> None:
    (add_tags if p.add else remove_tags)(p.notes, p.tags)
    return None


@registry.register("removeTags", params=TagsParams)
def ac_removeTags(p: TagsParams) -> None:
    remove_tags(p.notes, p.tags)
    return None


@registry.register("getTags")
def ac_getTags(params: Dict[str, Any]) -> List[str]:
    return all_tags()


@registry.register("notesModTime", params=DeleteNotesParams)
def ac_notesModTime(p: DeleteNotesParams) -> List[Dict[str, Any]]:
    return [item if item["mod"] is not None else {} for item in notes_mod_times(p.notes)]


class NoteUpdateAnyParams(BaseModel):
    """updateNote's payload: presence of a key is what dispatches."""
    class Config:
        extra = "allow"

    id: int
    fields: Optional[Dict[str, str]] = None
    tags: Optional[List[str]] = None
    audio: Any = None
    video: Any = None
    picture: Any = None


class UpdateNoteParams(BaseModel):
    note: NoteUpdateAnyParams


class UpdateNoteModelSpec(BaseModel):
    id: int
    modelName: str
    fields: Dict[str, str]
    tags: List[str] = []


class UpdateNoteModelParams(BaseModel):
    note: UpdateNoteModelSpec


class NoteIdParams(BaseModel):
    note: int


class UpdateNoteTagsParams(BaseModel):
    note: int
    tags: Any


class ReplaceTagsParams(BaseModel):
    notes: List[int]
    tag_to_replace: str
    replace_with_tag: str


class ReplaceTagsAllParams(BaseModel):
    tag_to_replace: str
    replace_with_tag: str


@registry.register("canAddNote", params=AddNoteParams)
def ac_canAddNote(p: AddNoteParams) -> bool:
    can_add, _ = _can_add(p.note)
    return can_add


@registry.register("canAddNoteWithErrorDetail", params=AddNoteParams)
def ac_canAddNoteWithErrorDetail(p: AddNoteParams) -> Dict[str, Any]:
    can_add, error = _can_add(p.note)
    # Success carries no "error" key at all.
    return {"canAdd": True} if can_add else {"canAdd": False, "error": error}


@registry.register("updateNote", params=UpdateNoteParams)
def ac_updateNote(p: UpdateNoteParams) -> None:
    spec = p.note
    updated = False
    if spec.fields is not None:
        ac_update_note_fields(spec.id, spec.fields, _resolve_media(spec))
        updated = True
    if spec.tags is not None:
        _set_note_tags(spec.id, spec.tags)
        updated = True
    if not updated:
        raise ValueError(NOTE_UPDATE_NO_INPUT)


@registry.register("updateNoteModel", params=UpdateNoteModelParams)
def ac_updateNoteModel(p: UpdateNoteModelParams) -> None:
    spec = p.note
    patch_note(spec.id, {"modelName": spec.modelName,
                         "fields": spec.fields, "tags": spec.tags})


def _set_note_tags(note_id: int, tags: Any) -> None:
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError(TAGS_MUST_BE_LIST)
    patch_note(note_id, {"tags": tags})


@registry.register("updateNoteTags", params=UpdateNoteTagsParams)
def ac_updateNoteTags(p: UpdateNoteTagsParams) -> None:
    _set_note_tags(p.note, p.tags)


@registry.register("getNoteTags", params=NoteIdParams)
def ac_getNoteTags(p: NoteIdParams) -> List[str]:
    notes = get_notes_by_ids([p.note], {"tags"})
    if not notes:
        raise ValueError(NOTE_NOT_FOUND.format(p.note))
    return list(notes[0].tags)


@registry.register("clearUnusedTags")
def ac_clearUnusedTags(params: Dict[str, Any]) -> None:
    # Returns None; the native POST /v1/tags:clear-unused reports a count.
    clear_unused_tags()


@registry.register("replaceTags", params=ReplaceTagsParams)
def ac_replaceTags(p: ReplaceTagsParams) -> None:
    replace_tag_on_notes(p.notes, p.tag_to_replace, p.replace_with_tag)


@registry.register("replaceTagsInAllNotes", params=ReplaceTagsAllParams)
def ac_replaceTagsInAllNotes(p: ReplaceTagsAllParams) -> None:
    replace_tag_everywhere(p.tag_to_replace, p.replace_with_tag)


@registry.register("removeEmptyNotes")
def ac_removeEmptyNotes(params: Dict[str, Any]) -> None:
    remove_unused_note_types()
