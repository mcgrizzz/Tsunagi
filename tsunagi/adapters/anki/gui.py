"""
Driving Anki's user interface: dialogs, the reviewer, and window state.

Every aqt import is function-local so this module stays importable with no Qt
present (the test suite runs headless), and every dialog touch goes through
call_on_main - Qt objects may only be created and mutated on the UI thread.

These are commands against the running application rather than edits to the
collection, so they use call_on_main rather than CollectionOp. The exceptions
are the ones that build a note first: that part is collection work.
"""
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ...shared.errors import (
    MissingReferenceError,
    ResourceNotFoundError,
    ValidationError,
)
from ..ops import (
    as_query_op,
    call_on_main,
    call_on_main_interactive,
    collection_op_call,
    recorded,
)

ADD_DIALOG_CLOSED = {"error": "Add Note dialog is not open", "code": 1}


def _mw() -> Any:
    from aqt import mw
    return mw


def _open_dialog(name: str) -> Any:
    import aqt
    return aqt.dialogs.open(name, aqt.mw)


def _existing_dialog(name: str) -> Any:
    """The open instance of a dialog, or None. Never opens one."""
    import aqt
    return (aqt.dialogs._dialogs.get(name) or [None, None])[1]


def _add_dialog() -> Any:
    """Resolve the supported draft window on the main thread."""
    if _existing_dialog("NewAddCards") is not None:
        raise ValidationError(
            "Anki's experimental Add window is open. Tsunagi cannot edit its "
            "draft yet. Finish or close that window before using API Add Cards actions."
        )
    return _existing_dialog("AddCards")


# ====================
# Browser
# ====================

def _apply_reorder(browser: Any, reorder: Dict[str, Any]) -> None:
    from aqt.qt import Qt

    if not isinstance(reorder, dict):
        raise ValidationError(f"reorderCards should be a dict: {reorder}")
    if not ("columnId" in reorder and "order" in reorder):
        # Canonical's message, unbalanced quote and all
        raise ValidationError('Must provide a "columnId" and a "order" property"')
    order = reorder["order"]
    if order not in ("ascending", "descending"):
        raise ValidationError(f"invalid card order: {order}")
    sort_order = (Qt.SortOrder.DescendingOrder if order == "descending"
                  else Qt.SortOrder.AscendingOrder)
    column_id = browser.table._model.active_column_index(reorder["columnId"])
    if column_id is None:
        raise ValidationError(f"invalid columnId: {reorder['columnId']}")
    browser.table._on_sort_column_changed(column_id, sort_order)


def _search_browser(browser: Any, done: Callable[..., None] = lambda exc=None: None) -> None:
    """Run the Browser's search once its editor can save, waiting through Qt
    callbacks (Anki's main thread never blocks). `done` is called exactly once,
    on the main thread: with no error when the search has run, or when the
    Browser closed or took a newer search (nothing is left to wait for); with
    AnkiBusyError when the editor isn't ready by the operation deadline."""
    import logging
    import time

    from ...shared.errors import AnkiBusyError

    settled = []

    def finish(exc: Optional[BaseException] = None) -> None:
        if not settled:
            settled.append(True)
            done(exc)

    def search():
        try:
            if hasattr(browser, "onSearch"):
                browser.onSearch()
            else:
                browser.onSearchActivated()
        except BaseException as exc:
            finish(exc)
            raise
        finish()

    web = getattr(getattr(browser, "editor", None), "web", None)
    if not callable(getattr(web, "evalWithCallback", None)):
        search()
        return

    token = object()
    browser._tsunagi_search_request = token
    if getattr(browser, "_tsunagi_search_web", None) is web:
        search()
        return

    from aqt.qt import QTimer

    from .. import ops

    timeout = ops.op_timeout()
    deadline = time.monotonic() + timeout

    def too_late() -> None:
        logging.getLogger(__name__).warning("Browser search skipped: editor did not become ready")
        finish(AnkiBusyError("Anki's Browser did not get ready to search in time"))

    def active():
        return (_existing_dialog("Browser") is browser
                and browser._tsunagi_search_request is token
                and getattr(getattr(browser, "editor", None), "web", None) is web)

    def retry():
        if time.monotonic() < deadline:
            QTimer.singleShot(50, probe)
        else:
            too_late()

    def ready(available):
        # Even after the deadline answered: the user still gets the search they asked for.
        if not active():
            finish()
        elif available:
            browser._tsunagi_search_web = web
            search()
        elif not settled:
            retry()

    def probe():
        if settled:
            return
        if not active():
            finish()
            return
        try:
            web.evalWithCallback("typeof saveNow === 'function'", ready)
        except RuntimeError:
            retry()  # The Qt page can be deleted while its callback is pending.

    # Qt drops a pending callback when its page is deleted; this ends the wait anyway.
    QTimer.singleShot(int(timeout * 1000) + 100, lambda: None if settled else too_late())
    probe()


def _browse(query: Optional[str], reorder: Optional[Dict[str, Any]],
            done: Callable[..., None] = lambda exc=None: None) -> None:
    """Runs on the Qt main thread. `done` is called once the Browser shows the
    search, sorted (see _search_browser); a search can end before the sort is
    applied, so its outcome waits for it."""
    browser = _open_dialog("Browser")
    browser.activateWindow()

    sorted_, held = [], []

    def searched(exc: Optional[BaseException] = None) -> None:
        if sorted_:
            done(exc)
        else:
            held.append(exc)

    if query is not None:
        browser.form.searchEdit.lineEdit().setText(query)
        _search_browser(browser, searched)
    else:
        held.append(None)

    if reorder is not None:
        _apply_reorder(browser, reorder)
    sorted_.append(True)
    if held:
        done(held[0])


@as_query_op
def reference_names(col: Any, deck_id: Optional[int] = None,
                    note_type_id: Optional[int] = None) -> Tuple[Optional[str], Optional[str]]:
    """The names of a deck and a note type given by id (None for one not given),
    for the GUI actions, which work by name; an unknown id is a ResourceNotFoundError."""
    deck = note_type = None
    if deck_id is not None:
        found = col.decks.get(int(deck_id), default=False)
        if not found:
            raise ResourceNotFoundError("Deck", int(deck_id))
        deck = found["name"]
    if note_type_id is not None:
        found = col.models.get(int(note_type_id))
        if not found:
            raise ResourceNotFoundError("Note type", int(note_type_id))
        note_type = found["name"]
    return deck, note_type


def open_browser(query: Optional[str] = None, reorder: Optional[Dict[str, Any]] = None, *,
                 before: Optional[Callable[[], None]] = None,
                 after: Optional[Callable[[Any], None]] = None) -> None:
    """Open the Browser and return once it shows the search (the native API's
    answer; AnkiConnect's guiBrowse doesn't wait). The request's thread waits;
    Anki's main thread only runs callbacks. On the main thread, `before` runs
    first (it can refuse, such as a 404) and `after(browser)` once the search shows."""
    def begin(ok: Callable[[Any], None], fail: Callable[[BaseException], None]) -> None:
        settled = []

        def end(exc: Optional[BaseException] = None) -> None:
            if not settled:
                settled.append(True)
                fail(exc) if exc is not None else ok(None)

        def shown(exc: Optional[BaseException] = None) -> None:
            if exc is None and after is not None and not settled:
                try:
                    after(_existing_dialog("Browser"))
                except BaseException as error:
                    exc = error
            end(exc)

        def run() -> None:
            try:
                if before is not None:
                    before()
                _browse(query, reorder, shown)
            except BaseException as exc:
                end(exc)

        _mw().taskman.run_on_main(run)

    recorded(begin, what="Opening the Browser")


def ac_browse(query: Any = None, reorder: Any = None) -> List[int]:
    """Preserve raw Qt arguments, search/sort order, and compatibility errors."""
    def _run() -> List[int]:
        try:
            _browse(query, reorder)
            return list(_mw().col.find_cards(query)) if query is not None else []
        except Exception as exc:
            raise ValueError(str(exc)) from exc
    return call_on_main(_run)


def ac_select_card(card_id: Any) -> bool:
    """Clear the current selection before passing the raw ID to the Browser."""
    def _select() -> bool:
        try:
            browser = _existing_dialog("Browser")
            if browser is None:
                return False
            browser.table.clear_selection()
            browser.table.select_single_card(card_id)
            return True
        except Exception as exc:
            raise ValueError(str(exc)) from exc
    return call_on_main(_select)


def select_card(card_id: int) -> bool:
    """False when no Browser is open (this does not open one) or it doesn't
    show the card; an unknown card is a ResourceNotFoundError."""
    def _select() -> bool:
        from aqt import mw

        if not mw.col.find_cards(f"cid:{int(card_id)}"):
            raise ResourceNotFoundError("Card", int(card_id))
        browser = _existing_dialog("Browser")
        if browser is None or browser.table._model.get_card_row(int(card_id)) is None:
            return False
        browser.table.clear_selection()
        browser.table.select_single_card(int(card_id))
        return True
    return call_on_main(_select)


def selected_notes() -> List[int]:
    def _read() -> List[int]:
        browser = _existing_dialog("Browser")
        if browser is None:
            return []
        return [int(n) for n in browser.selected_notes()]
    return call_on_main(_read)


def edit_note(note_id: int) -> bool:
    """
    Open the native API's Browser on one note, with typing going into its
    first field (Anki's Go > Note), once the Browser shows it.
    """
    def exists() -> None:
        from aqt import mw

        if not mw.col.find_notes(f"nid:{int(note_id)}"):
            raise ResourceNotFoundError("Note", int(note_id))

    def focus_note(browser: Any) -> None:
        # The Browser focuses its search bar; Go > Note moves to the editor once it has saved.
        if browser is not None and hasattr(browser, "onNote"):
            browser.onNote()

    open_browser(f"nid:{int(note_id)}", None, before=exists, after=focus_note)
    return True


def ac_edit_note(note_id: int) -> None:
    """Open the shim's standalone editor on the UI thread."""
    def _edit():
        from anki.errors import NotFoundError

        from ...http.compat.edit_dialog import open_editor

        try:
            open_editor(note_id)
        except (NotFoundError, LookupError, TypeError) as exc:
            raise ValueError(str(exc)) from exc

    call_on_main(_edit)


# ====================
# Add Cards
# ====================

def _run_gui_media(prepare, media, load_media):
    """Keep Qt-owned state in UI callbacks and run the media loader between them."""
    if load_media is None:
        # Native/pre-resolved calls retain their single UI-thread operation.
        def run():
            prepared = prepare()
            if prepared is None:
                return dict(ADD_DIALOG_CLOSED)
            apply_media, finish = prepared
            if media:
                apply_media(media)
            return finish()
        return call_on_main(run)

    prepared = call_on_main(prepare)
    if prepared is None:
        return dict(ADD_DIALOG_CLOSED)
    apply_media, finish = prepared

    class DialogChanged(Exception):
        pass

    def consume(item):
        if not call_on_main(apply_media, [item]):
            raise DialogChanged()
        return {}  # Already applied to the editor; do not retain downloaded bytes.

    try:
        load_media(consume)
    except DialogChanged:
        pass
    return call_on_main(finish)


def add_cards(note: Optional[Dict[str, Any]] = None,
              media: Optional[List[Dict[str, Any]]] = None, *,
              _compat: bool = False, _load_media: Optional[Callable] = None,
              files: Sequence[Any] = (), stored: Optional[List[Any]] = None) -> int:
    """
    Open the Add Cards dialog, optionally prefilled.

    Returns the id the editor is holding, which is 0 for a note that has not
    been added - Anki assigns an id on add, not on construction. Canonical
    returns the same 0; its comment about being "sure of the note id" predates
    that change.

    This is what asbplayer's "Open in Anki" calls.

    The native API's note takes exact field names, as a create does, and
    `files` (kind, name, data, fields), fetched beforehand: each is stored and
    referenced in its fields as a created note's are, and reported in `stored`.
    """
    from anki.notes import Note

    from .notes import (
        _ac_write_media,
        _apply_fields,
        _check_fields,
        _store_attachments,
        _with_references,
    )

    def _open_empty() -> int:
        _add_dialog()
        dialog = _open_dialog("AddCards")
        dialog.activateWindow()
        return int(dialog.editor.note.id)

    if note is None:
        return call_on_main(_open_empty)

    def _prepare_filled():
        from aqt import mw

        _add_dialog()
        col = mw.col
        deck = col.decks.by_name(note["deckName"])
        if deck is None:
            raise MissingReferenceError(f"deck was not found: {note['deckName']}" if _compat
                                        else f"Deck {note['deckName']} not found")
        col.decks.select(deck["id"])
        # Anki's deck dicts carry a stale 'mid' that set_current would persist
        # onto the deck; canonical lifts it out and puts it back afterwards.
        saved_mid = deck.pop("mid", None)

        model = col.models.by_name(note["modelName"])
        if model is None:
            raise MissingReferenceError(f"model was not found: {note['modelName']}" if _compat
                                        else f"Note type {note['modelName']} not found")
        col.models.set_current(model)
        col.models.update(model)

        new_note = Note(col, model)
        if _compat:
            if "fields" in note:
                for name, value in note["fields"].items():
                    if name in new_note:
                        new_note[name] = value
        else:
            _apply_fields(new_note, note.get("fields") or {}, model["name"])
            if files:
                _check_fields(new_note, [name for *_file, fields in files for name in fields], model["name"])
                for name, value in _with_references({k: new_note[k] for k in new_note.keys()}, list(files)).items():
                    new_note[name] = value
                (stored if stored is not None else []).extend(_store_attachments(col, new_note, list(files)))

        def check_collection():
            _add_dialog()
            if _mw().col is not col:
                raise ValidationError("collection changed while preparing media")

        def apply_media(items):
            check_collection()
            _ac_write_media(col, new_note, items)
            return True

        def finish():
            check_collection()
            if _compat:
                if "tags" in note:
                    new_note.tags = note["tags"]
            elif note.get("tags") is not None:
                new_note.tags = list(note["tags"])

            def show() -> None:
                # A discard prompt can keep this callback pending while the
                # user opens another editor or switches collections.
                try:
                    check_collection()
                except ValidationError as exc:
                    import logging

                    logging.getLogger(__name__).warning("Add Cards request skipped: %s", exc)
                    return
                dialog = _open_dialog("AddCards")
                if saved_mid:
                    deck["mid"] = saved_mid
                dialog.editor.set_note(new_note)
                dialog.activateWindow()
                if _compat:
                    _open_dialog("AddCards")
                dialog.setAndFocusNote(dialog.editor.note)

            # An already-open dialog has to close first, and closing is async, so
            # the refill rides on its callback.
            current = _existing_dialog("AddCards")
            if current is not None:
                current.closeWithCallback(show)
            else:
                show()
            return int(new_note.id)

        return apply_media, finish

    return _run_gui_media(_prepare_filled, media, _load_media)


def add_note_dialog_open() -> bool:
    """Check before preparing attachments for an existing Add Cards dialog."""
    def _check() -> bool:
        dialog = _add_dialog()
        return dialog is not None and hasattr(dialog, "editor")
    return call_on_main(_check)


def set_add_note_data(note: Dict[str, Any], append: bool = False,
                      media: Optional[List[Dict[str, Any]]] = None, *,
                      _compat: bool = False, _load_media: Optional[Callable] = None) -> Any:
    """
    Amend the open Add Cards dialog. Returns canonical's error DICT rather
    than raising when the dialog is closed - clients branch on that shape.
    """
    from .notes import _ac_write_media

    def _prepare():
        from aqt import mw

        dialog = _add_dialog()
        if dialog is None or not hasattr(dialog, "editor"):
            return None

        col = mw.col
        if "deckName" in note:
            deck = col.decks.by_name(note["deckName"])
            if deck is None:
                raise MissingReferenceError(f'Deck "{note["deckName"]}" not found' if _compat
                                            else f"Deck {note['deckName']} not found")
            dialog.set_deck(deck["id"])
        if "modelName" in note:
            model = col.models.by_name(note["modelName"])
            if model is None:
                raise MissingReferenceError(f'Model "{note["modelName"]}" not found' if _compat
                                            else f"Note type {note['modelName']} not found")
            dialog.set_note_type(model["id"])

        editor_note = dialog.editor.note
        if _compat:
            fields = note["fields"] if "fields" in note else {}
        else:
            fields = note.get("fields") or {}
        for name, value in fields.items():
            if name not in editor_note:
                raise ValidationError(f'Field "{name}" not found in current note')
            editor_note[name] = (str(editor_note[name]) + str(value)) if append else value

        if _compat:
            if "tags" in note:
                if append:
                    tags = note["tags"] if isinstance(note["tags"], list) else [note["tags"]]
                    editor_note.tags = list(set(editor_note.tags + tags))
                else:
                    editor_note.tags = note["tags"]
        elif note.get("tags") is not None:
            tags = note["tags"] if isinstance(note["tags"], list) else [note["tags"]]
            editor_note.tags = (sorted(set(editor_note.tags) | set(tags))
                                if append else list(tags))
        def current():
            return (mw.col is col and _add_dialog() is dialog
                    and getattr(dialog, "editor", None) is not None
                    and dialog.editor.note is editor_note)

        def apply_media(items):
            if not current():
                return False
            _ac_write_media(col, editor_note, items)
            return True

        def finish():
            if not current():
                return dict(ADD_DIALOG_CLOSED)
            dialog.editor.loadNote()
            return True

        return apply_media, finish

    return _run_gui_media(_prepare, media, _load_media)


# ====================
# Reviewer
# ====================

def review_active() -> bool:
    def _check() -> bool:
        mw = _mw()
        return mw.reviewer.card is not None and mw.state == "review"
    return call_on_main(_check)


def current_card(*, _compat: bool = False) -> Optional[Dict[str, Any]]:
    """
    The card being reviewed, or None when no review is in progress.

    Canonical raises instead; the native route reports null and the compat
    handler turns that back into canonical's error.
    """
    def _read() -> Optional[Dict[str, Any]]:
        from .cards import _next_reviews

        mw = _mw()
        if mw.reviewer.card is None or mw.state != "review":
            return None
        card = mw.reviewer.card
        model = card.note_type()
        note = card.note()
        buttons = [b[0] for b in mw.reviewer._answerButtonList()]
        return {
            "cardId": int(card.id),
            "fields": {f["name"]: {"value": note.fields[f["ord"]], "order": f["ord"]}
                       for f in model["flds"]},
            "fieldOrder": int(card.ord),
            "question": card.question(),
            "answer": card.answer(),
            "buttons": buttons,
            "nextReviews": ([mw.col.sched.nextIvlStr(card, ease, True) for ease in buttons]
                            if _compat else _next_reviews(mw.col, card.id)),
            "modelName": model["name"],
            "deckName": mw.col.decks.name(card.did),
            "css": model["css"],
            "template": card.template()["name"],
        }
    return call_on_main(_read)


def show_question() -> bool:
    def _show() -> bool:
        mw = _mw()
        if mw.reviewer.card is None or mw.state != "review":
            return False
        mw.reviewer._showQuestion()
        return True
    return call_on_main(_show)


def show_answer() -> bool:
    def _show() -> bool:
        mw = _mw()
        if mw.reviewer.card is None or mw.state != "review":
            return False
        mw.reviewer._showAnswer()
        return True
    return call_on_main(_show)


def answer_card(ease: int) -> bool:
    """False when no review is active, the answer isn't showing, or ease is out of range."""
    def _answer() -> bool:
        mw = _mw()
        if mw.reviewer.card is None or mw.state != "review":
            return False
        if mw.reviewer.state != "answer":
            return False
        # The v3 scheduler always offers four answer buttons.
        if ease <= 0 or ease > 4:
            return False
        mw.reviewer._answerCard(ease)
        return True
    return call_on_main(_answer)


def start_card_timer() -> bool:
    def _start() -> bool:
        mw = _mw()
        card = mw.reviewer.card
        if card is None or mw.state != "review":
            return False
        card.start_timer()
        return True
    return call_on_main(_start)


def play_audio() -> bool:
    def _play() -> bool:
        mw = _mw()
        if mw.reviewer.card is None or mw.state != "review":
            return False
        mw.reviewer.replayAudio()
        return True
    return call_on_main(_play)


def undo() -> bool:
    def _undo() -> bool:
        _mw().undo()
        return True
    return call_on_main(_undo)


def _undo_step(col: Any) -> Any:
    from anki.errors import UndoEmpty

    try:
        return col.undo()
    except UndoEmpty:
        return None


def undo_last() -> Optional[str]:
    """Undo the last step and name it (Anki's label, such as "Add Note"); None
    when there is nothing to undo. Unlike undo(), which starts Anki's own undo
    and returns at once, this waits for the result. Anki's windows refresh as
    after Ctrl+Z: the operation's changes reach them the same way."""
    from aqt import gui_hooks

    out = collection_op_call(_undo_step)
    if out is None:
        return None
    call_on_main(gui_hooks.state_did_undo, out)  # as Anki's own undo announces it
    return out.operation


# ====================
# Navigation and windows
# ====================

def deck_browser() -> bool:
    def _go() -> bool:
        _mw().moveToState("deckBrowser")
        return True
    return call_on_main(_go)


def deck_overview(name: str) -> bool:
    def _go() -> bool:
        mw = _mw()
        deck = mw.col.decks.by_name(name)
        if deck is None:
            return False
        mw.col.decks.select(deck["id"])
        mw.onOverview()
        return True
    return call_on_main(_go)


def deck_review(name: str) -> bool:
    def _go() -> bool:
        mw = _mw()
        deck = mw.col.decks.by_name(name)
        if deck is None:
            return False
        mw.col.decks.select(deck["id"])
        # Straight into the reviewer, which is what Anki's own "Study Now"
        # button does. Canonical routes through the overview first
        # (guiDeckOverview, then moveToState) and that races: the overview's
        # web view finishes loading after the reviewer has been shown and
        # repaints over it, so you land on the deck page with mw.state already
        # "review" - and have to call it twice to actually start studying.
        mw.moveToState("review")
        return True
    return call_on_main(_go)


def import_file(path: Optional[str] = None, *, _compat: bool = False) -> bool:
    """Request the import UI; compatibility calls wait for Anki's GUI call."""
    def _import() -> bool:
        from aqt import mw
        from aqt.import_export.importing import import_file as _do
        from aqt.import_export.importing import prompt_for_file_then_import

        if _compat:
            from aqt.qt import Qt

            on_top = getattr(Qt, "WindowStaysOnTopHint", None)
            if on_top is None:
                on_top = getattr(getattr(Qt, "WindowType", None), "WindowStaysOnTopHint", None)
            if on_top is not None:
                try:
                    mw.setWindowFlags(mw.windowFlags() | on_top)
                    mw.show()
                finally:
                    mw.setWindowFlags(mw.windowFlags() & ~on_top)
                    mw.show()

        if path is None or (not _compat and not path):
            prompt_for_file_then_import(mw)
        else:
            _do(mw, path)
        return True
    if _compat:
        return call_on_main_interactive(_import)

    def schedule() -> bool:
        from aqt import mw
        from aqt.qt import QTimer

        from ...shared.errors import CollectionUnavailableError

        collection = mw.col

        def launch() -> None:
            from aqt import mw as current_window

            if current_window is not mw or mw.col is not collection or collection is None:
                raise CollectionUnavailableError()
            # Exceptions after acknowledgement go through Anki's Qt error handler.
            _import()

        QTimer.singleShot(0, launch)
        return True

    return call_on_main_interactive(schedule)


def exit_anki() -> bool:
    """
    Close Anki. Deliberately deferred: the reply has to reach the caller
    before the process that is sending it goes away.
    """
    def _exit() -> bool:
        from aqt import mw
        from aqt.qt import QTimer

        QTimer.singleShot(1000, mw.close)
        return True
    return call_on_main(_exit)
