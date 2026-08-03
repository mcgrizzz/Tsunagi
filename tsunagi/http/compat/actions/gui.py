"""
AnkiConnect compatibility handlers for GUI actions.

Pure translation over adapters/anki/gui.py, which the /v1/gui:* routes use
too. The adapter owns the aqt work and keeps its imports function-local, so
this module stays importable with no Qt present.
"""
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki import gui as g
from ....adapters.anki.cards import find_card_ids
from ..registry import registry


class GuiBrowseParams(BaseModel):
    query: Optional[str] = None
    # Deliberately untyped: canonical validates the shape itself and reports
    # 'reorderCards should be a dict: <value>', which a pydantic type error
    # would pre-empt with a different message.
    reorderCards: Optional[Any] = None


class CardParams(BaseModel):
    card: int


class NoteParams(BaseModel):
    note: int


class GuiAddCardsParams(BaseModel):
    note: Optional[Dict[str, Any]] = None


class GuiAddNoteSetDataParams(BaseModel):
    note: Dict[str, Any]
    append: bool = False


class EaseParams(BaseModel):
    ease: int


class DeckParams(BaseModel):
    name: str


class ImportFileParams(BaseModel):
    path: Optional[str] = None


def _media_of(note: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Resolve audio/video/picture attachments off a raw note dict.

    _resolve_media reads them with getattr, so wrap the dict rather than
    duplicating the download logic.
    """
    from .notes import _resolve_media

    return _resolve_media(SimpleNamespace(**note))


# ====================
# Browser
# ====================

@registry.register("guiBrowse", params=GuiBrowseParams)
def ac_guiBrowse(p: GuiBrowseParams) -> List[int]:
    # Dialog first, then the ids - canonical order, so the result reflects
    # the state after the search ran.
    g.open_browser(p.query, p.reorderCards)
    return find_card_ids(p.query) if p.query is not None else []


@registry.register("guiSelectCard", params=CardParams)
def ac_guiSelectCard(p: CardParams) -> bool:
    return g.select_card(p.card)


@registry.register("guiSelectNote", params=CardParams)
def ac_guiSelectNote(p: CardParams) -> bool:
    """
    Canonical's own deprecated alias: it selects a CARD despite the name, and
    prints a deprecation notice. Compat-only - /v1 exposes select-card alone.
    """
    return g.select_card(p.card)


@registry.register("guiSelectedNotes")
def ac_guiSelectedNotes(params: Optional[Dict[str, Any]] = None) -> List[int]:
    return g.selected_notes()


@registry.register("guiEditNote", params=NoteParams)
def ac_guiEditNote(p: NoteParams) -> None:
    g.edit_note(p.note)
    return None


# ====================
# Add Cards
# ====================

@registry.register("guiAddCards", params=GuiAddCardsParams)
def ac_guiAddCards(p: GuiAddCardsParams) -> int:
    return g.add_cards(p.note, _media_of(p.note) if p.note else None)


@registry.register("guiAddNoteSetData", params=GuiAddNoteSetDataParams)
def ac_guiAddNoteSetData(p: GuiAddNoteSetDataParams) -> Any:
    return g.set_add_note_data(p.note, p.append, _media_of(p.note))


# ====================
# Reviewer
# ====================

@registry.register("guiReviewActive")
def ac_guiReviewActive(params: Optional[Dict[str, Any]] = None) -> bool:
    return g.review_active()


@registry.register("guiCurrentCard")
def ac_guiCurrentCard(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    card = g.current_card()
    if card is None:
        # Canonical raises here; the native route reports null instead.
        raise ValueError("Gui review is not currently active.")
    return card


@registry.register("guiStartCardTimer")
def ac_guiStartCardTimer(params: Optional[Dict[str, Any]] = None) -> bool:
    return g.start_card_timer()


@registry.register("guiShowQuestion")
def ac_guiShowQuestion(params: Optional[Dict[str, Any]] = None) -> bool:
    return g.show_question()


@registry.register("guiShowAnswer")
def ac_guiShowAnswer(params: Optional[Dict[str, Any]] = None) -> bool:
    return g.show_answer()


@registry.register("guiAnswerCard", params=EaseParams)
def ac_guiAnswerCard(p: EaseParams) -> bool:
    return g.answer_card(p.ease)


@registry.register("guiUndo")
def ac_guiUndo(params: Optional[Dict[str, Any]] = None) -> bool:
    return g.undo()


@registry.register("guiPlayAudio")
def ac_guiPlayAudio(params: Optional[Dict[str, Any]] = None) -> bool:
    return g.play_audio()


# ====================
# Navigation and windows
# ====================

@registry.register("guiDeckBrowser")
def ac_guiDeckBrowser(params: Optional[Dict[str, Any]] = None) -> None:
    g.deck_browser()
    return None


@registry.register("guiDeckOverview", params=DeckParams)
def ac_guiDeckOverview(p: DeckParams) -> bool:
    return g.deck_overview(p.name)


@registry.register("guiDeckReview", params=DeckParams)
def ac_guiDeckReview(p: DeckParams) -> bool:
    return g.deck_review(p.name)


@registry.register("guiImportFile", params=ImportFileParams)
def ac_guiImportFile(p: ImportFileParams) -> None:
    g.import_file(p.path)
    return None


@registry.register("guiCheckDatabase")
def ac_guiCheckDatabase(params: Optional[Dict[str, Any]] = None) -> bool:
    from ....adapters.anki.collection import check_database

    check_database()
    return True


@registry.register("guiExitAnki")
def ac_guiExitAnki(params: Optional[Dict[str, Any]] = None) -> None:
    g.exit_anki()
    return None
