from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, StrictBool, validator

# ----------------- Response Schemas -----------------
from .creation import CreationFailure, CreationResult
from .media import MediaStored, MediaUpload
from .wrappers import NULLABLE, RequestBody, derived


class NoteField(BaseModel):
    """
    One field of a note. Deliberately mirrors NoteTypeField's shape so the query
    DSL reads the same on both resources: where=fields[].name==Front,
    select=fields[].(name,value).
    """
    class Config:
        extra = "ignore"
        allow_population_by_field_name = True

    name: str = Field(description="Field name.")
    value: str = Field(description="Field content, as stored (HTML).")
    index: int = Field(description="Field position in the note type, from 0.")


class NoteInfo(BaseModel):
    class Config:
        extra = "ignore"
        allow_population_by_field_name = True

    id: int = Field(description="Note id: its creation time in epoch milliseconds.")
    guid: str = Field("", description=(
        "Globally unique id Anki uses to match the note across syncs and imports."))
    # Anki's wire name for a note's notetype id
    note_type_id: int = Field(0, alias="mid", description="Id of the note's note type.")
    note_type_name: str = Field("", description="Name of the note's note type.", **derived("note_types"))
    modified: int = Field(0, alias="mod", description="Last modified, Unix seconds.")
    usn: int = Field(0, description="Update sequence number for syncing; -1 means changed since the last sync.")
    tags: List[str] = Field(default_factory=list, description="The note's tags.")
    # The first field's value: what Anki's duplicate check compares.
    first_field: str = Field("", description="The first field's content, as stored (HTML).")
    # NOT aliased to "flds": on a note that's Anki's positional list of raw
    # strings, so the alias would describe something else entirely.
    fields: List[NoteField] = Field(default_factory=list, description="The note's fields, in note type order.",
                                    **derived("note_types"))
    # Costs one backend call per note (Anki has no batch lookup), so it is
    # only populated when the caller's select/where references it.
    cards: Optional[List[int]] = Field(None, description="Ids of the note's cards, in template order.")


# ----------------- Request Schemas -----------------


class NoteFieldValue(RequestBody):
    """Array form of a field on write."""
    name: str
    value: str = ""
    # So a field read from GET (name, value, index) can be sent back as it is.
    index: Optional[int] = Field(None, description="Accepted and ignored: a field's position comes from its note type")


# Writes accept either {"Front": "犬"} or [{"name": "Front", "value": "犬"}].
FieldsInput = Union[Dict[str, str], List[NoteFieldValue]]


class DuplicateScopeOptions(RequestBody):
    """AnkiConnect's duplicateScopeOptions, with the same names and defaults."""
    class Config:
        allow_population_by_field_name = True

    deck_name: Optional[str] = Field(
        alias="deckName", default=None,
        description="Deck scope: check this deck instead of the note's own deck.")
    check_children: StrictBool = Field(
        alias="checkChildren", default=False,
        description="Deck scope: also check the deck's subdecks.")
    check_all_note_types: StrictBool = Field(
        alias="checkAllNoteTypes", default=False,
        description="Match notes of every note type, not just the candidate's.")


class NoteAttachment(MediaUpload):
    """A file stored with the note, as in AnkiConnect's addNote."""
    fields: List[str] = Field(default_factory=list,
                              description="Fields the file's reference is appended to; none stores it only.")


Attachments = Optional[Union[List[NoteAttachment], NoteAttachment]]


class NoteFiles(RequestBody):
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


def tags_without_spaces(tags: Optional[List[str]]) -> Optional[List[str]]:
    """Anki splits a tag on whitespace when it saves the note, so "a b" would
    quietly become two tags (6.75). The AnkiConnect side keeps that."""
    for tag in tags or []:
        if any(c.isspace() for c in tag):
            raise ValueError(f"a tag can't contain a space: {tag!r} would be stored as "
                             f"{len(tag.split())} tags")
    return tags


class NoteInput(RequestBody):
    """A note as creation, checks and upsert take it; NoteCreate adds files."""
    class Config:
        allow_population_by_field_name = True
        # Without smart_union pydantic v1 tries Dict[str, str] first and
        # mangles the array form into a dict of stringified indices.
        smart_union = True

    note_type_id: Optional[int] = Field(alias="noteTypeId", default=None)
    note_type_name: Optional[str] = Field(alias="noteTypeName", default=None)
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
                     "check_all_note_types is used, notes match on the first field's checksum, "
                     "as in AnkiConnect."),
    )

    _tags = validator("tags", allow_reuse=True)(tags_without_spaces)


class NoteCreate(NoteInput, NoteFiles):
    pass


class NotePatch(NoteFiles):
    class Config:
        allow_population_by_field_name = True
        smart_union = True

    # Partial: only the named fields are overwritten.
    fields: Optional[FieldsInput] = None
    tags: Optional[List[str]] = None                                  # replaces
    add_tags: Optional[List[str]] = Field(alias="addTags", default=None)
    remove_tags: Optional[List[str]] = Field(alias="removeTags", default=None)
    _tags = validator("tags", "add_tags", "remove_tags", allow_reuse=True)(tags_without_spaces)
    # Retype the note. Requires `fields`: the new note type's fields start empty.
    note_type_id: Optional[int] = Field(alias="noteTypeId", default=None)
    note_type_name: Optional[str] = Field(alias="noteTypeName", default=None)


def unique_ids(ids: List[int]) -> List[int]:
    """An id sent twice counts once (Anki's batch ops fail on a repeat)."""
    return list(dict.fromkeys(ids))


class NoteIds(RequestBody):
    """Body for the batch note verbs, as CardIds is for cards."""
    class Config:
        allow_population_by_field_name = True

    note_ids: List[int] = Field(
        alias="noteIds",
        description="A note id sent twice counts once; a missing note is skipped.")

    _unique = validator("note_ids", allow_reuse=True)(unique_ids)


# ----------------- Duplicate/empty check -----------------


class NoteCheckResult(BaseModel):
    index: int = Field(description="Zero-based position in the request.")
    can_add: bool
    state: Literal["normal", "empty", "duplicate", "missing_cloze", "invalid", "unknown"] = Field(description=(
        "normal: it can be added. empty: its first field is empty. duplicate: it duplicates a note "
        "(it can still be added with allow_duplicate). missing_cloze: a cloze note without a cloze. "
        "invalid: the request names a deck, note type or field that doesn't exist (see reason). "
        "unknown: Anki gave a reason Tsunagi doesn't name."))
    reason: Optional[str] = Field(None, description=(
        "Why it can't be added: the state, or what is wrong for invalid; null when it can."), **NULLABLE)
    duplicate_note_ids: Optional[List[int]] = Field(
        default_factory=list,
        description="Matching note IDs, with include=duplicate_ids; null without it.", **NULLABLE,
    )


class NoteCheckResponse(BaseModel):
    results: List[NoteCheckResult]
    stats: dict


class NoteCreated(BaseModel):
    index: int = Field(description="Zero-based position in the submitted array; 0 for one object.")
    id: int
    cards: Optional[List[int]] = Field(default=None, description="The note's card IDs, with include=cards; null without it.",
                                       **NULLABLE)
    files: Optional[List[MediaStored]] = Field(
        default=None,
        description=("The note's audio, video and picture files as stored, in that order, as POST /v1/media "
                     "reports them. `filename` differs from `requested_filename` when Anki renamed the file; "
                     "references in the fields a file lists follow the rename, others don't. Present when "
                     "the note had files; null when it had none."), **NULLABLE)


class AttachmentRef(BaseModel):
    kind: Literal["audio", "video", "picture"]
    position: int = Field(description="Zero-based position in that kind's list; 0 for one object.")
    filename: Optional[str] = Field(default=None, description="The filename sent; null when none was.", **NULLABLE)


class NoteCreateFailure(CreationFailure):
    code: Literal["duplicate", "invalid_note", "invalid_attachment", "anki_error"] = Field(description=(
        "duplicate: it duplicates a note (see duplicate_note_ids). invalid_note: it can't be made as "
        "sent, such as a deck, note type or field that doesn't exist (see message). "
        "invalid_attachment: one of its files (see attachment). anki_error: Anki refused it (see message)."))
    duplicate_note_ids: Optional[List[int]] = Field(
        default=None,
        description="For code 'duplicate', with include=duplicate_ids: the existing notes it duplicates.", **NULLABLE)
    attachment: Optional[AttachmentRef] = Field(
        default=None, description="For code 'invalid_attachment': the file that failed.", **NULLABLE)


class NoteCreateResponse(CreationResult[NoteCreated]):
    failed: List[NoteCreateFailure] = Field(default_factory=list)


# ----------------- Upsert (backlog 7.1) -----------------

FieldRule = Literal["keep", "replace", "replace_if_empty", "append"]


class UpsertMatch(RequestBody):
    field: Optional[str] = Field(
        default=None,
        description=("Field whose content identifies the note, compared exactly (case-insensitive) "
                     "within the note type. Default: Anki's duplicate check (the first field, "
                     "HTML ignored), including duplicateScope and its options."))


class OnMatch(RequestBody):
    fields: Dict[str, FieldRule] = Field(
        default_factory=dict,
        description=("Per field: keep, replace (unless the new value is empty), replace_if_empty, "
                     "or append (after `separator`, skipped when the value is already there). "
                     "\"*\" sets the rule for the others; default replace_if_empty. Fields the "
                     "request does not send are never touched."))
    tags: Literal["union", "replace", "keep"] = Field(
        default="union", description="union adds the request's tags; replace sets them; keep leaves them.")
    separator: str = Field(default="<br>", description="Put between the old and new value by append.")


class NoteUpsert(NoteInput):
    match: UpsertMatch = Field(default_factory=UpsertMatch)
    on_match: OnMatch = Field(alias="onMatch", default_factory=OnMatch)


class NoteUpsertFailure(CreationFailure):
    code: Literal["duplicate", "invalid_note", "ambiguous", "anki_error"] = Field(description=(
        "duplicate: no note matched and the new one would duplicate one. invalid_note: it can't be "
        "made as sent, such as a field that doesn't exist (see message). ambiguous: "
        "more than one note matched. anki_error: Anki refused it (see message)."))


class NoteUpdated(BaseModel):
    index: int = Field(description="Zero-based position in the submitted array; 0 for one object.")
    id: int
    fields_changed: List[str] = Field(description="Fields whose value changed; empty when nothing did.")
    tags_changed: bool
    cards: Optional[List[int]] = Field(default=None, description="The note's card IDs, with include=cards; null without it.",
                                       **NULLABLE)


class NoteUpsertResponse(BaseModel):
    created: List[NoteCreated] = Field(default_factory=list)
    updated: List[NoteUpdated] = Field(default_factory=list)
    failed: List[NoteUpsertFailure] = Field(default_factory=list)
