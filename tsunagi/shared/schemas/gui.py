from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GuiResult(BaseModel):
    """
    Did the UI do the thing.

    False rather than an error for the ordinary "not right now" cases - no
    Browser open, no review in progress, no such deck - because those are
    states a client polls for, not mistakes it made.
    """
    ok: bool = True
    stats: Dict[str, Any] = Field(default_factory=dict)


class BrowseRequest(BaseModel):
    query: Optional[str] = Field(None, description="Anki search to run in the Browser")
    # Deliberately untyped: the shape is validated by hand so the error text
    # matches AnkiConnect's, which a pydantic type error would pre-empt.
    reorder: Optional[Any] = Field(
        None, description='{"columnId": ..., "order": "ascending"|"descending"}')


class BrowseResult(BaseModel):
    card_ids: List[int] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


class CardIdRequest(BaseModel):
    card_id: int


class NoteIdRequest(BaseModel):
    note_id: int


class NoteIdList(BaseModel):
    note_ids: List[int] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


class AddCardsRequest(BaseModel):
    """Everything optional: an empty body just opens the dialog."""
    deck_name: Optional[str] = Field(None, alias="deckName")
    model_name: Optional[str] = Field(None, alias="modelName")
    fields: Optional[Dict[str, str]] = None
    tags: Optional[List[str]] = None

    class Config:
        allow_population_by_field_name = True


class AddCardsResult(BaseModel):
    # The id the editor is holding, which is 0 for a prefilled note: nothing
    # has been added yet, and Anki does not assign an id until the user
    # confirms the dialog. AnkiConnect returns the same 0 despite its docs
    # promising "the note id of the note that was created".
    note_id: Optional[int] = None
    stats: Dict[str, Any] = Field(default_factory=dict)


class SetAddNoteDataRequest(AddCardsRequest):
    append: bool = Field(
        False, description="Append to existing field values and tags instead of replacing")


class SetAddNoteDataResult(BaseModel):
    ok: bool = False
    # Set when the Add Cards dialog is not open; canonical reports this rather
    # than raising, and clients branch on it.
    error: Optional[str] = None
    code: Optional[int] = None
    stats: Dict[str, Any] = Field(default_factory=dict)


class CurrentCard(BaseModel):
    """Null when no review is in progress."""
    card_id: int
    fields: Dict[str, Dict[str, Any]]
    field_order: int
    question: str
    answer: str
    buttons: List[int]
    next_reviews: Optional[List[str]] = None
    model_name: str
    deck_name: str
    css: str
    template: str


class CurrentCardResult(BaseModel):
    card: Optional[CurrentCard] = None
    review_active: bool = False
    stats: Dict[str, Any] = Field(default_factory=dict)


class AnswerRequest(BaseModel):
    ease: int = Field(..., ge=1, le=4, description="Answer button, 1-4")


class DeckNameRequest(BaseModel):
    name: str


class ImportFileRequest(BaseModel):
    path: Optional[str] = Field(
        None, description="File to import; omit to let the user pick one")
