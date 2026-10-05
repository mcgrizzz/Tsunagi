"""
Routes that drive Anki's user interface.

Verb routes rather than resources - `POST /v1/gui:browse` opens a window, it
does not create one - following the same `resource:verb` convention as
/v1/cards:suspend and /v1/note-types:find-replace.

Everything here needs a live Qt main window, so it is exercised by the manual
smoke checklist rather than the test suite. The handlers stay thin for exactly
that reason: the logic they call lives in adapters/anki/gui.py, which the
AnkiConnect shim uses too.
"""
import time
from typing import Callable, Optional, Tuple

from fastapi import APIRouter, Body

from ...adapters.anki import gui as g
from ...adapters.anki.cards import find_card_ids
from ...shared.errors import ResourceNotFoundError, handle_mutation_errors
from ...shared.permissions import requires
from ...shared.schemas.decks import DeckRequest
from ...shared.schemas.gui import (
    AddCardsRequest,
    AddCardsResult,
    AnswerRequest,
    BrowseRequest,
    BrowseResult,
    CardIdRequest,
    CurrentCardResult,
    GuiResult,
    ImportFileRequest,
    NoteIdList,
    NoteIdRequest,
    SetAddNoteDataRequest,
    UndoResult,
)
from .notes import fetch_note_files

router = APIRouter()


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


def _verb(path: str, summary: str, description: str, response_model=GuiResult,
          permission: str = "gui") -> Callable:
    def decorate(fn: Callable) -> Callable:
        operation_id = "gui" + "".join(p.capitalize() for p in path.split("-"))
        return router.post(
            f"/v1/gui:{path}",
            response_model=response_model,
            summary=summary,
            description=description,
            tags=["GUI"],
            operation_id=operation_id,
            openapi_extra=requires(permission),
        )(handle_mutation_errors(path)(fn))
    return decorate


# ====================
# Browser
# ====================

@_verb("browse", "Open the Browser",
       "Opens the card Browser, optionally running a search and sorting it. "
       "Returns the card ids the query matches.",
       response_model=BrowseResult)
def browse(body: Optional[BrowseRequest] = Body(None)) -> BrowseResult:
    start = time.perf_counter()
    body = body or BrowseRequest()
    # Dialog first, then the ids, so the result reflects the state after the
    # search ran - canonical's order.
    g.open_browser(body.query, body.reorder)
    ids = find_card_ids(body.query) if body.query is not None else []
    return BrowseResult(card_ids=ids, stats=_stats(start))


@_verb("select-card", "Select a card in the Browser",
       "Selects one card in an already-open Browser. False when none is open (this "
       "does not open one) or its search doesn't show the card; 404 for a card that "
       "doesn't exist.")
def select_card(body: CardIdRequest = Body(...)) -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.select_card(body.card_id), stats=_stats(start))


@_verb("edit-note", "Open a note for editing",
       "Opens the Browser focused on one note. Deviation from AnkiConnect, "
       "which opens its own standalone editor dialog.")
def edit_note(body: NoteIdRequest = Body(...)) -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.edit_note(body.note_id), stats=_stats(start))


@router.get(
    "/v1/gui/selected-notes",
    openapi_extra=requires("gui"),
    response_model=NoteIdList,
    summary="Notes selected in the Browser",
    description="Empty when no Browser is open.",
    tags=["GUI"],
    operation_id="guiSelectedNotes",
)
@handle_mutation_errors("read")
def selected_notes() -> NoteIdList:
    start = time.perf_counter()
    return NoteIdList(note_ids=g.selected_notes(), stats=_stats(start))


def _names(deck_id: Optional[int], deck_name: Optional[str], note_type_id: Optional[int] = None,
           note_type_name: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """The deck and note type by name, for the GUI actions: an id wins, and is looked up."""
    if deck_id is None and note_type_id is None:
        return deck_name, note_type_name
    deck, note_type = g.reference_names(deck_id, note_type_id)
    return deck or deck_name, note_type or note_type_name


# ====================
# Add Cards
# ====================

@_verb("add-cards", "Open Add Cards",
       "Opens the Add Cards dialog, prefilled when a note is given: its deck and note type "
       "(each by name or id) and any fields, tags and files (audio, video, picture, as "
       "POST /v1/notes takes them; each is stored now and referenced in its fields). The "
       "note is NOT added - the user still confirms. Returns the id the editor holds.",
       response_model=AddCardsResult)
def add_cards(body: Optional[AddCardsRequest] = Body(None)) -> AddCardsResult:
    start = time.perf_counter()
    body = body or AddCardsRequest()
    if body.deck_id is None and not body.deck_name:
        return AddCardsResult(note_id=g.add_cards(None), stats=_stats(start))
    files = fetch_note_files(body)   # before the dialog: a file that can't be read opens nothing
    deck, note_type = _names(body.deck_id, body.deck_name, body.note_type_id, body.note_type_name)
    spec = {"deckName": deck, "modelName": note_type, "fields": body.fields or {}, "tags": body.tags}
    stored: list = []
    note_id = g.add_cards(spec, files=files, stored=stored)
    return AddCardsResult(note_id=note_id, files=stored or None, stats=_stats(start))


@_verb("set-add-note-data", "Amend the open Add Cards dialog",
       "Sets deck, note type (each by name or id), fields or tags on an already-open "
       "Add Cards dialog. False when it isn't open.")
def set_add_note_data(body: SetAddNoteDataRequest = Body(...)) -> GuiResult:
    start = time.perf_counter()
    deck, note_type = _names(body.deck_id, body.deck_name, body.note_type_id, body.note_type_name)
    spec = {}
    if deck:
        spec["deckName"] = deck
    if note_type:
        spec["modelName"] = note_type
    if body.fields is not None:
        spec["fields"] = body.fields
    if body.tags is not None:
        spec["tags"] = body.tags

    return GuiResult(ok=g.set_add_note_data(spec, body.append) is True, stats=_stats(start))


# ====================
# Reviewer
# ====================

@router.get(
    "/v1/gui/current-card",
    openapi_extra=requires("gui"),
    response_model=CurrentCardResult,
    summary="The card being reviewed",
    description="`card` is null and `review_active` false when no review is in progress.",
    tags=["GUI"],
    operation_id="guiCurrentCard",
)
@handle_mutation_errors("read")
def current_card() -> CurrentCardResult:
    start = time.perf_counter()
    card = g.current_card()
    if card is None:
        return CurrentCardResult(card=None, review_active=False, stats=_stats(start))
    return CurrentCardResult(
        card={
            "card_id": card["cardId"], "fields": card["fields"],
            "field_order": card["fieldOrder"], "question": card["question"],
            "answer": card["answer"], "buttons": card["buttons"],
            "next_reviews": card["nextReviews"], "note_type_name": card["modelName"],
            "deck_name": card["deckName"], "css": card["css"],
            "template": card["template"],
        },
        review_active=True, stats=_stats(start))


@_verb("show-question", "Show the question",
       "Re-displays the question side. False when no review is in progress.")
def show_question() -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.show_question(), stats=_stats(start))


@_verb("show-answer", "Show the answer",
       "Reveals the answer side. False when no review is in progress.")
def show_answer() -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.show_answer(), stats=_stats(start))


@_verb("answer-card", "Answer the current card",
       "Presses an answer button (1-4). False unless the answer is showing.",
       permission="write:cards")
def answer_card(body: AnswerRequest = Body(...)) -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.answer_card(body.rating), stats=_stats(start))


@_verb("start-card-timer", "Restart the answer timer",
       "Resets how long the current card is recorded as having taken.")
def start_card_timer() -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.start_card_timer(), stats=_stats(start))


@_verb("play-audio", "Replay the card's audio",
       "Replays audio on the card being reviewed.")
def play_audio() -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.play_audio(), stats=_stats(start))


@_verb("undo", "Undo",
       "Undoes the last step, as Ctrl+Z would, and names it; `undone` is null when there "
       "is nothing to undo.",
       response_model=UndoResult, permission="write")  # can revert any kind of change
def undo() -> UndoResult:
    start = time.perf_counter()
    return UndoResult(undone=g.undo_last(), stats=_stats(start))


# ====================
# Navigation
# ====================

@_verb("deck-browser", "Show the deck list", "Returns Anki to the deck list.")
def deck_browser() -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.deck_browser(), stats=_stats(start))


@_verb("deck-overview", "Show a deck's overview",
       "Selects a deck, by name or id, and shows its overview screen. 404 when there is no such deck.")
def deck_overview(body: DeckRequest = Body(...)) -> GuiResult:
    start = time.perf_counter()
    name, _ = _names(body.deck_id, body.deck_name)
    if not g.deck_overview(name):
        raise ResourceNotFoundError("Deck", name)
    return GuiResult(stats=_stats(start))


@_verb("deck-review", "Start reviewing a deck",
       "Selects a deck, by name or id, and enters the reviewer. 404 when there is no such deck.")
def deck_review(body: DeckRequest = Body(...)) -> GuiResult:
    start = time.perf_counter()
    name, _ = _names(body.deck_id, body.deck_name)
    if not g.deck_review(name):
        raise ResourceNotFoundError("Deck", name)
    return GuiResult(stats=_stats(start))


@_verb("import-file", "Request the import dialog",
       "Schedules Anki's import UI, on the given file if one is named. The path "
       "is resolved on the machine running Anki. Returns ok=true once the UI "
       "thread accepts the launch request; this does not confirm that a file "
       "was selected or imported. Cancellation and later errors are handled in "
       "Anki, and no job ID is created.")
def import_file(body: Optional[ImportFileRequest] = Body(None)) -> GuiResult:
    start = time.perf_counter()
    body = body or ImportFileRequest()
    return GuiResult(ok=g.import_file(body.path), stats=_stats(start))


@_verb("exit", "Close Anki",
       "Shuts Anki down. Deferred by a second so this reply reaches you first.",
       permission="manage")
def exit_anki() -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.exit_anki(), stats=_stats(start))
