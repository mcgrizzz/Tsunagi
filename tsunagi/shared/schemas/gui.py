from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, root_validator, validator

from .media import MediaStored
from .notes import NoteFiles, tags_without_spaces
from .wrappers import NULLABLE, RequestBody


class GuiResult(BaseModel):
    """
    Did the UI do the thing.

    False rather than an error for the ordinary "not right now" cases - no
    Browser open, no review in progress - because those are states a client
    polls for, not mistakes it made. Something named that doesn't exist is a 404.
    """
    ok: bool = True
    stats: Dict[str, Any] = Field(default_factory=dict)


class UndoResult(BaseModel):
    undone: Optional[str] = Field(description=(
        "The step undone, as Anki names it (\"Add Note\"); null when there was nothing to undo."),
        **NULLABLE)
    stats: Dict[str, Any] = Field(default_factory=dict)


class BrowseRequest(RequestBody):
    query: Optional[str] = Field(None, description="Anki search to run in the Browser")
    # Deliberately untyped: the shape is validated by hand so the error text
    # matches AnkiConnect's, which a pydantic type error would pre-empt.
    reorder: Optional[Any] = Field(
        None, description='{"columnId": ..., "order": "ascending"|"descending"}')


class BrowseResult(BaseModel):
    card_ids: List[int] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


class CardIdRequest(RequestBody):
    card_id: int


class NoteIdRequest(RequestBody):
    note_id: int


class NoteIdList(BaseModel):
    note_ids: List[int] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


class AddCardsNote(RequestBody):
    """A deck and a note type each by name or id (the id when both are sent), as note writes take them."""
    deck_id: Optional[int] = Field(None, alias="deckId")
    deck_name: Optional[str] = Field(None, alias="deckName")
    note_type_id: Optional[int] = Field(None, alias="noteTypeId")
    note_type_name: Optional[str] = Field(None, alias="noteTypeName")
    fields: Optional[Dict[str, str]] = None
    tags: Optional[List[str]] = None

    class Config:
        allow_population_by_field_name = True

    _tags = validator("tags", allow_reuse=True)(tags_without_spaces)


class AddCardsRequest(AddCardsNote, NoteFiles):
    """An empty body just opens the dialog; a note to prefill it names its deck and note type.
    Files are stored and referenced in their fields as POST /v1/notes does it."""
    @root_validator(skip_on_failure=True, allow_reuse=True)
    def _deck_and_note_type(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        given = [v for v in values.values() if v is not None]
        deck = values.get("deck_id") is not None or values.get("deck_name")
        note_type = values.get("note_type_id") is not None or values.get("note_type_name")
        if given and not (deck and note_type):
            raise ValueError("a note to prefill Add Cards names its deck and its note type")
        return values


class AddCardsResult(BaseModel):
    # The id the editor is holding, which is 0 for a prefilled note: nothing
    # has been added yet, and Anki does not assign an id until the user
    # confirms the dialog. AnkiConnect returns the same 0 despite its docs
    # promising "the note id of the note that was created".
    note_id: Optional[int] = None
    files: Optional[List[MediaStored]] = Field(None, description=(
        "The prefilled note's files as stored, as POST /v1/notes reports them; null when it had none."),
        **NULLABLE)
    stats: Dict[str, Any] = Field(default_factory=dict)


class SetAddNoteDataRequest(AddCardsNote):
    append: bool = Field(
        False, description="Append to existing field values and tags instead of replacing")


class CurrentCard(BaseModel):
    """Null when no review is in progress."""
    card_id: int
    fields: Dict[str, Dict[str, Any]]
    field_order: int
    question: str
    answer: str
    buttons: List[int]
    next_reviews: Optional[List[str]] = None
    note_type_name: str
    deck_name: str
    css: str
    template: str


class CurrentCardResult(BaseModel):
    card: Optional[CurrentCard] = None
    review_active: bool = False
    stats: Dict[str, Any] = Field(default_factory=dict)


class AnswerRequest(RequestBody):
    rating: int = Field(..., ge=1, le=4, description="Answer button, 1-4")




class ImportFileRequest(RequestBody):
    path: Optional[str] = Field(
        None, description="File to import; omit to let the user pick one")
