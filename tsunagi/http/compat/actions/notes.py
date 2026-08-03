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
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from ....adapters.anki.cards import find_card_ids
from ....adapters.anki.notes import (
    ac_add_note,
    ac_check_note,
    ac_update_note_fields,
    delete_notes,
    find_note_ids,
    get_notes_by_ids,
    notes_mod_times,
    profile_name,
)
from ....adapters.anki.tags import add_tags, all_tags, remove_tags
from ..errors import NOTES_INFO_NO_INPUT
from ..registry import registry


class MediaSpec(BaseModel):
    filename: str
    data: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    skipHash: Optional[str] = None
    fields: Optional[List[str]] = None
    deleteExisting: Optional[bool] = None   # note-spec default is falsy


class NoteSpec(BaseModel):
    class Config:
        smart_union = True

    deckName: str
    modelName: str
    fields: Dict[str, str]
    tags: List[str] = []
    options: Optional[Dict[str, Any]] = None
    audio: Optional[Union[MediaSpec, List[Optional[MediaSpec]]]] = None
    video: Optional[Union[MediaSpec, List[Optional[MediaSpec]]]] = None
    picture: Optional[Union[MediaSpec, List[Optional[MediaSpec]]]] = None


class NoteUpdateSpec(BaseModel):
    class Config:
        smart_union = True

    id: int
    fields: Dict[str, str]
    audio: Optional[Union[MediaSpec, List[Optional[MediaSpec]]]] = None
    video: Optional[Union[MediaSpec, List[Optional[MediaSpec]]]] = None
    picture: Optional[Union[MediaSpec, List[Optional[MediaSpec]]]] = None


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
    query: Optional[str] = None


class DeleteNotesParams(BaseModel):
    notes: List[int]


# ---- media attached to a note spec -------------------------------------

_MARKUP = {"picture": '<img src="{}">', "audio": "[sound:{}]", "video": "[sound:{}]"}


def _as_list(value) -> List[MediaSpec]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [m for m in items if m is not None]


def _resolve_media(spec) -> List[Dict[str, Any]]:
    """
    Download/decode every media attachment on the request thread (never
    inside an Anki op - a slow download would hold the collection), returning
    plain dicts the adapter can write.
    """
    from ....adapters.settings import settings
    from ...v1.media import _fetch_url

    out: List[Dict[str, Any]] = []
    for kind in ("audio", "video", "picture"):
        for media in _as_list(getattr(spec, kind, None)):
            entry: Dict[str, Any] = {
                "kind": kind,
                "filename": media.filename,
                "fields": list(media.fields or []),
                "markup": _MARKUP[kind],
                # Absent key means falsy here - opposite of standalone
                # storeMediaFile's default. Canonical quirk, preserved.
                "delete_existing": bool(media.deleteExisting),
                "data": None,
                "error": None,
            }
            try:
                if media.data:
                    data = base64.b64decode(media.data)
                elif media.path:
                    if not settings.get("media_allow_local_path", False):
                        raise ValueError("local 'path' uploads are disabled (media_allow_local_path)")
                    with open(media.path, "rb") as fh:
                        data = fh.read()
                elif media.url:
                    data = _fetch_url(media.url)
                else:
                    raise ValueError('You must provide a "data", "path", or "url" field.')
                if media.skipHash is not None and hashlib.md5(data).hexdigest() == media.skipHash:
                    data = None  # caller already has it: store nothing, append nothing
                entry["data"] = data
            except Exception as e:
                # Canonical appends the HTML-escaped message into the target
                # fields and still creates the note.
                entry["error"] = (str(e).replace("&", "&amp;")
                                  .replace("<", "&lt;").replace(">", "&gt;"))
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
        # Deliberate deviation: a read-only probe must not write media files
        # into the collection (canonical does, via createNote). Yomitan
        # strips media from probe notes anyway.
        ac_check_note(spec.deckName, spec.modelName, spec.fields, spec.options or {})
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
    if p.notes is None and p.query is None:
        raise ValueError(NOTES_INFO_NO_INPUT)
    ids = find_note_ids(p.query) if p.query is not None else list(p.notes)

    found = {int(n.id): n for n in get_notes_by_ids(ids)}
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
            "cards": info.cards or [],
        })
    return out


@registry.register("findNotes", params=FindNotesParams)
def ac_findNotes(p: FindNotesParams) -> List[int]:
    if p.query is None:
        return []
    return find_note_ids(p.query)


@registry.register("findCards", params=FindNotesParams)
def ac_findCards(p: FindNotesParams) -> List[int]:
    if p.query is None:
        return []
    return find_card_ids(p.query)


@registry.register("deleteNotes", params=DeleteNotesParams)
def ac_deleteNotes(p: DeleteNotesParams) -> None:
    delete_notes(p.notes)
    return None


class TagsParams(BaseModel):
    notes: List[int]
    tags: str          # space-separated, per AnkiConnect


@registry.register("addTags", params=TagsParams)
def ac_addTags(p: TagsParams) -> None:
    add_tags(p.notes, p.tags)
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
    return notes_mod_times(p.notes)
