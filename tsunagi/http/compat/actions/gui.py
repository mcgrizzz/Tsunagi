"""
AnkiConnect compatibility handlers for GUI actions.

Pure translation over adapters/anki/gui.py, which the /v1/gui:* routes use
too. The adapter owns the aqt work and keeps its imports function-local, so
this module stays importable with no Qt present.
"""
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki import gui as g
from ..registry import registry


def _gui_call(operation: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Expose Anki's GUI errors through the compatibility envelope."""
    try:
        return operation(*args, **kwargs)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


class GuiBrowseParams(BaseModel):
    query: Any = None
    # Deliberately untyped: canonical validates the shape itself and reports
    # 'reorderCards should be a dict: <value>', which a pydantic type error
    # would pre-empt with a different message.
    reorderCards: Optional[Any] = None


class CardParams(BaseModel):
    card: Any = ...


class SelectNoteParams(BaseModel):
    note: Any = ...


class NoteParams(BaseModel):
    note: int


class GuiAddCardsParams(BaseModel):
    note: Any = None


class GuiAddNoteSetDataParams(BaseModel):
    note: Any = ...
    append: Any = False


class EaseParams(BaseModel):
    ease: Any = ...


class DeckParams(BaseModel):
    name: Any = ...


class ImportFileParams(BaseModel):
    path: Any = None


def _media_of(note: Any, *, on_resolved=None) -> List[Dict[str, Any]]:
    """Prepare raw attachments on the request thread for the GUI adapter."""
    from .notes import _resolve_media

    if isinstance(note, dict):
        return _resolve_media(note, on_resolved=on_resolved)
    try:
        note.get("audio")
    except Exception as exc:
        # Surface malformed notes when media is applied, after GUI validation.
        entry = {"abort_error": str(exc)}
        return [on_resolved(entry) if on_resolved else entry]
    return []


# ====================
# Browser
# ====================

@registry.register("guiBrowse", params=GuiBrowseParams)
def ac_guiBrowse(p: GuiBrowseParams) -> List[int]:
    return g.ac_browse(p.query, p.reorderCards)


@registry.register("guiSelectCard", params=CardParams)
def ac_guiSelectCard(p: CardParams) -> bool:
    return g.ac_select_card(p.card)


@registry.register("guiSelectNote", params=SelectNoteParams)
def ac_guiSelectNote(p: SelectNoteParams) -> bool:
    """
    Canonical's own deprecated alias: it selects a CARD despite the name, and
    retains the old `note` argument. Compat-only - /v1 exposes select-card alone.
    """
    return g.ac_select_card(p.note)


@registry.register("guiSelectedNotes")
def ac_guiSelectedNotes(params: Optional[Dict[str, Any]] = None) -> List[int]:
    return g.selected_notes()


@registry.register("guiEditNote", params=NoteParams)
def ac_guiEditNote(p: NoteParams) -> None:
    g.ac_edit_note(p.note)
    return None


# ====================
# Add Cards
# ====================

@registry.register("guiAddCards", params=GuiAddCardsParams)
def ac_guiAddCards(p: GuiAddCardsParams) -> int:
    try:
        return g.add_cards(p.note, _compat=True,
                           _load_media=lambda consume: _media_of(p.note, on_resolved=consume))
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@registry.register("guiAddNoteSetData", params=GuiAddNoteSetDataParams)
def ac_guiAddNoteSetData(p: GuiAddNoteSetDataParams) -> Any:
    if not g.add_note_dialog_open():
        return dict(g.ADD_DIALOG_CLOSED)
    try:
        return g.set_add_note_data(p.note, p.append, _compat=True,
                                   _load_media=lambda consume: _media_of(p.note, on_resolved=consume))
    except Exception as exc:
        raise ValueError(str(exc)) from exc


# ====================
# Reviewer
# ====================

@registry.register("guiReviewActive")
def ac_guiReviewActive(params: Optional[Dict[str, Any]] = None) -> bool:
    return _gui_call(g.review_active)


@registry.register("guiCurrentCard")
def ac_guiCurrentCard(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    card = _gui_call(g.current_card, _compat=True)
    if card is None:
        # Canonical raises here; the native route reports null instead.
        raise ValueError("Gui review is not currently active.")
    return card


@registry.register("guiStartCardTimer")
def ac_guiStartCardTimer(params: Optional[Dict[str, Any]] = None) -> bool:
    return _gui_call(g.start_card_timer)


@registry.register("guiShowQuestion")
def ac_guiShowQuestion(params: Optional[Dict[str, Any]] = None) -> bool:
    return _gui_call(g.show_question)


@registry.register("guiShowAnswer")
def ac_guiShowAnswer(params: Optional[Dict[str, Any]] = None) -> bool:
    return _gui_call(g.show_answer)


@registry.register("guiAnswerCard", params=EaseParams)
def ac_guiAnswerCard(p: EaseParams) -> bool:
    return _gui_call(g.answer_card, p.ease)


@registry.register("guiUndo")
def ac_guiUndo(params: Optional[Dict[str, Any]] = None) -> bool:
    return _gui_call(g.undo)


@registry.register("guiPlayAudio")
def ac_guiPlayAudio(params: Optional[Dict[str, Any]] = None) -> bool:
    return _gui_call(g.play_audio)


# ====================
# Navigation and windows
# ====================

@registry.register("guiDeckBrowser")
def ac_guiDeckBrowser(params: Optional[Dict[str, Any]] = None) -> None:
    _gui_call(g.deck_browser)
    return None


@registry.register("guiDeckOverview", params=DeckParams)
def ac_guiDeckOverview(p: DeckParams) -> bool:
    return _gui_call(g.deck_overview, p.name)


@registry.register("guiDeckReview", params=DeckParams)
def ac_guiDeckReview(p: DeckParams) -> bool:
    return _gui_call(g.deck_review, p.name)


@registry.register("guiImportFile", params=ImportFileParams)
def ac_guiImportFile(p: ImportFileParams) -> None:
    _gui_call(g.import_file, p.path, _compat=True)
    return None


@registry.register("guiCheckDatabase")
def ac_guiCheckDatabase(params: Optional[Dict[str, Any]] = None) -> bool:
    from ....adapters.anki.collection import check_database

    _gui_call(check_database)
    return True


@registry.register("guiExitAnki")
def ac_guiExitAnki(params: Optional[Dict[str, Any]] = None) -> None:
    _gui_call(g.exit_anki)
    return None
