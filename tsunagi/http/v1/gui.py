"""
Routes that drive Anki's user interface.

Verb routes rather than resources - `POST /v1/gui:browse` opens a window, it
does not create one - following the same `resource:verb` convention as
/v1/cards:suspend and /v1/models:find-replace.

Everything here needs a live Qt main window, so it is exercised by the manual
smoke checklist rather than the test suite. The handlers stay thin for exactly
that reason: the logic they call lives in adapters/anki/gui.py, which the
AnkiConnect shim uses too.
"""
import time
from typing import Callable, Optional

from fastapi import APIRouter, Body

from ...adapters.anki import gui as g
from ...adapters.anki.cards import find_card_ids
from ...shared.errors import handle_mutation_errors
from ...shared.schemas.gui import (
    AddCardsRequest,
    AddCardsResult,
    AnswerRequest,
    BrowseRequest,
    BrowseResult,
    CardIdRequest,
    CurrentCardResult,
    DeckNameRequest,
    GuiResult,
    ImportFileRequest,
    NoteIdList,
    NoteIdRequest,
    SetAddNoteDataRequest,
    SetAddNoteDataResult,
)

router = APIRouter()


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


def _verb(path: str, summary: str, description: str, response_model=GuiResult) -> Callable:
    def decorate(fn: Callable) -> Callable:
        operation_id = "gui" + "".join(p.capitalize() for p in path.split("-"))
        return router.post(
            f"/v1/gui:{path}",
            response_model=response_model,
            summary=summary,
            description=description,
            tags=["GUI"],
            operation_id=operation_id,
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
       "Selects one card in an already-open Browser. False when none is open - "
       "this does not open one.")
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


# ====================
# Add Cards
# ====================

@_verb("add-cards", "Open Add Cards",
       "Opens the Add Cards dialog, prefilled when a note is given. The note is "
       "NOT added - the user still confirms. Returns the id the editor holds.",
       response_model=AddCardsResult)
def add_cards(body: Optional[AddCardsRequest] = Body(None)) -> AddCardsResult:
    start = time.perf_counter()
    body = body or AddCardsRequest()
    spec = None
    if body.deck_name or body.model_name:
        spec = {"deckName": body.deck_name, "modelName": body.model_name,
                "fields": body.fields or {}, "tags": body.tags}
    return AddCardsResult(note_id=g.add_cards(spec), stats=_stats(start))


@_verb("set-add-note-data", "Amend the open Add Cards dialog",
       "Sets deck, notetype, fields or tags on an already-open Add Cards dialog. "
       "Reports an error payload rather than failing when it is closed.",
       response_model=SetAddNoteDataResult)
def set_add_note_data(body: SetAddNoteDataRequest = Body(...)) -> SetAddNoteDataResult:
    start = time.perf_counter()
    spec = {}
    if body.deck_name:
        spec["deckName"] = body.deck_name
    if body.model_name:
        spec["modelName"] = body.model_name
    if body.fields is not None:
        spec["fields"] = body.fields
    if body.tags is not None:
        spec["tags"] = body.tags

    result = g.set_add_note_data(spec, body.append)
    if result is True:
        return SetAddNoteDataResult(ok=True, stats=_stats(start))
    return SetAddNoteDataResult(ok=False, error=result["error"], code=result["code"],
                                stats=_stats(start))


# ====================
# Reviewer
# ====================

@router.get(
    "/v1/gui/current-card",
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
            "next_reviews": card["nextReviews"], "model_name": card["modelName"],
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
       "Presses an answer button (1-4). False unless the answer is showing.")
def answer_card(body: AnswerRequest = Body(...)) -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.answer_card(body.ease), stats=_stats(start))


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


@_verb("undo", "Undo", "Undoes the last operation, as Ctrl+Z would.")
def undo() -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.undo(), stats=_stats(start))


# ====================
# Navigation
# ====================

@_verb("deck-browser", "Show the deck list", "Returns Anki to the deck list.")
def deck_browser() -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.deck_browser(), stats=_stats(start))


@_verb("deck-overview", "Show a deck's overview",
       "Selects a deck and shows its overview screen. False when there is no such deck.")
def deck_overview(body: DeckNameRequest = Body(...)) -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.deck_overview(body.name), stats=_stats(start))


@_verb("deck-review", "Start reviewing a deck",
       "Selects a deck and enters the reviewer. False when there is no such deck.")
def deck_review(body: DeckNameRequest = Body(...)) -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.deck_review(body.name), stats=_stats(start))


@_verb("import-file", "Open the import dialog",
       "Opens Anki's import dialog, on the given file if one is named. The path "
       "is resolved on the machine running Anki.")
def import_file(body: Optional[ImportFileRequest] = Body(None)) -> GuiResult:
    start = time.perf_counter()
    body = body or ImportFileRequest()
    return GuiResult(ok=g.import_file(body.path), stats=_stats(start))


@_verb("exit", "Close Anki",
       "Shuts Anki down. Deferred by a second so this reply reaches you first.")
def exit_anki() -> GuiResult:
    start = time.perf_counter()
    return GuiResult(ok=g.exit_anki(), stats=_stats(start))
