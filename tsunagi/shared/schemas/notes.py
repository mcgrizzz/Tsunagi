from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, StrictBool, validator

# ----------------- Response Schemas -----------------
from .creation import CreationFailure, CreationResult
from .media import MediaStored, MediaUpload


class NoteField(BaseModel):
    """
    One field of a note. Deliberately mirrors ModelField's shape so the query
    DSL reads the same on both resources: where=fields[].name==Front,
    select=fields[].(name,value).
    """
    class Config:
        extra = "ignore"
        allow_population_by_field_name = True

    name: str
    value: str
    ord: int


class NoteInfo(BaseModel):
    class Config:
        extra = "ignore"
        allow_population_by_field_name = True

    id: int
    guid: str = ""
    # Anki's wire name for a note's notetype id
    model_id: int = Field(alias="mid", default=0)
    model_name: str = ""
    mod: int = 0
    usn: int = 0
    tags: List[str] = Field(default_factory=list)
    # The first field's value: what Anki's duplicate check compares.
    first_field: str = ""
    # NOT aliased to "flds": on a note that's Anki's positional list of raw
    # strings, so the alias would describe something else entirely.
    fields: List[NoteField] = Field(default_factory=list)
    # Costs one backend call per note (Anki has no batch lookup), so it is
    # only populated when the caller's select/where references it.
    cards: Optional[List[int]] = None


# ----------------- Request Schemas -----------------


class NoteFieldValue(BaseModel):
    """Array form of a field on write ('ord' accepted and ignored)."""
    class Config:
        extra = "ignore"

    name: str
    value: str = ""


# Writes accept either {"Front": "犬"} or [{"name": "Front", "value": "犬"}].
FieldsInput = Union[Dict[str, str], List[NoteFieldValue]]


class DuplicateScopeOptions(BaseModel):
    """AnkiConnect's duplicateScopeOptions, with the same names and defaults."""
    class Config:
        allow_population_by_field_name = True

    deck_name: Optional[str] = Field(
        alias="deckName", default=None,
        description="Deck scope: check this deck instead of the note's own deck.")
    check_children: StrictBool = Field(
        alias="checkChildren", default=False,
        description="Deck scope: also check the deck's subdecks.")
    check_all_models: StrictBool = Field(
        alias="checkAllModels", default=False,
        description="Match notes of every note type, not just the candidate's.")


class NoteAttachment(MediaUpload):
    """A file stored with the note, as in AnkiConnect's addNote."""
    fields: List[str] = Field(default_factory=list,
                              description="Fields the file's reference is appended to; none stores it only.")


Attachments = Optional[Union[List[NoteAttachment], NoteAttachment]]


class NoteFiles(BaseModel):
    """Files sent with a note, on creation and on PATCH."""
    # Stored with the note, with [sound:...] or <img src="..."> appended to
    # their fields: one object or a list each, as in AnkiConnect.
    audio: Attachments = None
    video: Attachments = None
    picture: Attachments = None

    def attachments(self) -> List[tuple]:
        """(kind, attachment) pairs, audio first, as AnkiConnect orders them."""
        out = []
        for kind in ("audio", "video", "picture"):
            value = getattr(self, kind)
            out += [(kind, a) for a in (value if isinstance(value, list) else [value] if value else [])]
        return out


class NoteCreate(NoteFiles):
    class Config:
        allow_population_by_field_name = True
        # Without smart_union pydantic v1 tries Dict[str, str] first and
        # mangles the array form into a dict of stringified indices.
        smart_union = True

    model_id: Optional[int] = Field(alias="modelId", default=None)
    model_name: Optional[str] = Field(alias="modelName", default=None)
    deck_id: Optional[int] = Field(alias="deckId", default=None)
    # Never auto-creates a deck; POST /v1/decks does that explicitly.
    deck_name: Optional[str] = Field(alias="deckName", default=None)
    fields: FieldsInput
    tags: List[str] = Field(default_factory=list)
    allow_duplicate: bool = Field(alias="allowDuplicate", default=False)
    duplicate_scope: Optional[Literal["collection", "deck"]] = Field(
        alias="duplicateScope", default=None,
        description="Where to look for duplicates: the whole collection (default) or one deck.",
    )
    duplicate_scope_options: Optional[DuplicateScopeOptions] = Field(
        alias="duplicateScopeOptions", default=None,
        description=("Deck and note-type options for the duplicate check. When deck scope or "
                     "check_all_models is used, notes match on the first field's checksum, "
                     "as in AnkiConnect."),
    )


class NotePatch(NoteFiles):
    class Config:
        allow_population_by_field_name = True
        smart_union = True

    # Partial: only the named fields are overwritten.
    fields: Optional[FieldsInput] = None
    tags: Optional[List[str]] = None                                  # replaces
    add_tags: Optional[List[str]] = Field(alias="addTags", default=None)
    remove_tags: Optional[List[str]] = Field(alias="removeTags", default=None)
    # Retype the note. Requires `fields`: the new model's fields start empty.
    model_id: Optional[int] = Field(alias="modelId", default=None)
    model_name: Optional[str] = Field(alias="modelName", default=None)


def unique_ids(ids: List[int]) -> List[int]:
    """An id sent twice counts once (Anki's batch ops fail on a repeat)."""
    return list(dict.fromkeys(ids))


class NoteIds(BaseModel):
    """Body for the batch note verbs, as CardIds is for cards."""
    class Config:
        allow_population_by_field_name = True

    note_ids: List[int] = Field(
        alias="noteIds",
        description="A note id sent twice counts once; a missing note is skipped.")

    _unique = validator("note_ids", allow_reuse=True)(unique_ids)


# ----------------- Duplicate/empty check -----------------


class NoteCheckRequest(BaseModel):
    class Config:
        allow_population_by_field_name = True

    notes: List[NoteCreate]


class NoteCheckResult(BaseModel):
    index: int                       # position in the request
    can_add: bool
    state: str                       # normal|empty|duplicate|missing_cloze|unknown_model|unknown_deck|unknown_field
    reason: Optional[str] = None
    duplicate_note_ids: Optional[List[int]] = Field(
        default_factory=list, nullable=True,
        description="Matching note IDs, with include=duplicate_ids; null without it.",
    )


class NoteCheckResponse(BaseModel):
    results: List[NoteCheckResult]
    stats: dict


class NoteCreated(BaseModel):
    index: int = Field(description="Zero-based position in the submitted array; 0 for one object.")
    id: int
    cards: Optional[List[int]] = Field(default=None, description="Present when include=cards was requested.")
    files: Optional[List[MediaStored]] = Field(
        default=None,
        description=("The note's audio, video and picture files as stored, in that order, as POST /v1/media "
                     "reports them. `filename` differs from `requested_filename` when Anki renamed the file; "
                     "references in the fields a file lists follow the rename, others don't. Present when "
                     "the note had files."))


class AttachmentRef(BaseModel):
    kind: Literal["audio", "video", "picture"]
    position: int = Field(description="Zero-based position in that kind's list; 0 for one object.")
    filename: Optional[str] = Field(default=None, description="The filename sent, if any.")


class NoteCreateFailure(CreationFailure):
    duplicate_note_ids: Optional[List[int]] = Field(
        default=None,
        description="For code 'duplicate', with include=duplicate_ids: the existing notes it duplicates.")
    attachment: Optional[AttachmentRef] = Field(
        default=None, description="For code 'invalid_attachment': the file that failed.")


class NoteCreateResponse(CreationResult[NoteCreated]):
    failed: List[NoteCreateFailure] = Field(default_factory=list)


# ----------------- Upsert (backlog 7.1) -----------------

FieldRule = Literal["keep", "replace", "replace_if_empty", "append"]


class UpsertMatch(BaseModel):
    field: Optional[str] = Field(
        default=None,
        description=("Field whose content identifies the note, compared exactly (case-insensitive) "
                     "within the note type. Default: Anki's duplicate check (the first field, "
                     "HTML ignored), including duplicateScope and its options."))


class OnMatch(BaseModel):
    fields: Dict[str, FieldRule] = Field(
        default_factory=dict,
        description=("Per field: keep, replace (unless the new value is empty), replace_if_empty, "
                     "or append (after `separator`, skipped when the value is already there). "
                     "\"*\" sets the rule for the others; default replace_if_empty. Fields the "
                     "request does not send are never touched."))
    tags: Literal["union", "replace", "keep"] = Field(
        default="union", description="union adds the request's tags; replace sets them; keep leaves them.")
    separator: str = Field(default="<br>", description="Put between the old and new value by append.")


class NoteUpsert(NoteCreate):
    match: UpsertMatch = Field(default_factory=UpsertMatch)
    on_match: OnMatch = Field(alias="onMatch", default_factory=OnMatch)


class NoteUpdated(BaseModel):
    index: int = Field(description="Zero-based position in the submitted array; 0 for one object.")
    id: int
    fields_changed: List[str] = Field(description="Fields whose value changed; empty when nothing did.")
    tags_changed: bool
    cards: Optional[List[int]] = Field(default=None, description="Present when include=cards was requested.")


class NoteUpsertResponse(BaseModel):
    created: List[NoteCreated] = Field(default_factory=list)
    updated: List[NoteUpdated] = Field(default_factory=list)
    failed: List[CreationFailure] = Field(default_factory=list)
