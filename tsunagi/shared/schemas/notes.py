from __future__ import annotations

from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field

# ----------------- Response Schemas -----------------


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


class NoteCreate(BaseModel):
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
    duplicate_scope: Optional[str] = Field(alias="duplicateScope", default=None)


class NotePatch(BaseModel):
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
    duplicate_note_ids: List[int] = Field(default_factory=list)


class NoteCheckResponse(BaseModel):
    results: List[NoteCheckResult]
    stats: dict
