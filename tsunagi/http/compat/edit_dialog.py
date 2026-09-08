"""Standalone AnkiConnect editor. Imported only from the Qt main thread."""
import aqt
import aqt.editor
import aqt.forms.editcurrent
from anki.consts import QUEUE_TYPE_SUSPENDED
from anki.errors import NotFoundError
from anki.utils import ids2str
from aqt import gui_hooks
from aqt.browser.previewer import MultiCardPreviewer
from aqt.qt import QAction, QKeySequence, QMainWindow, Qt
from aqt.utils import restoreGeom, saveGeom, tooltip

DIALOG_TAG = "tsunagi.AnkiConnectEdit"
SEARCH_TAG = "tsunagi.edit.history"


def _history():
    state = getattr(aqt.mw, "_tsunagi_edit_history", None)
    if state is None or state[0] is not aqt.mw.col:
        state = (aqt.mw.col, [])
        aqt.mw._tsunagi_edit_history = state
    return state[1]


def _prune_history():
    ids = _history()
    if ids:
        valid = set(aqt.mw.col.db.list("select id from notes where id in " + ids2str(ids)))
        ids[:] = [nid for nid in ids if nid in valid]
    return ids


def _record(note_id):
    ids = _prune_history()
    if note_id in ids:
        ids.remove(note_id)
    ids.append(note_id)
    del ids[:-25]


def _search_history(context):
    if context.search != SEARCH_TAG:
        return
    ids = _prune_history()
    context.search = " or ".join(f"nid:{nid}" for nid in ids) or "nid:0"
    if context.browser.table._state.sort_column == SEARCH_TAG:
        cases = " ".join(f"when {nid} then {index}" for index, nid in enumerate(reversed(ids)))
        context.order = f"case c.nid {cases} end asc" if cases else False


def open_editor(note_id):
    # Validate before registration/opening, so invalid IDs never create a window.
    note = aqt.mw.col.get_note(note_id)
    previous_hook = getattr(aqt.mw, "_tsunagi_edit_search_hook", None)
    if previous_hook is not _search_history:
        if previous_hook is not None:
            gui_hooks.browser_will_search.remove(previous_hook)
        gui_hooks.browser_will_search.append(_search_history)
        aqt.mw._tsunagi_edit_search_hook = _search_history
    existing = aqt.dialogs._dialogs.get(DIALOG_TAG, [None, None])[1]
    # Reloads refresh the creator without losing an existing editor or its edits.
    aqt.dialogs.register_dialog(DIALOG_TAG, EditDialog, existing)
    return aqt.dialogs.open(DIALOG_TAG, note)


class NotePreviewer(MultiCardPreviewer):
    def __init__(self, cards, on_close):
        super().__init__(parent=None, mw=aqt.mw, on_close=on_close)
        self.cards = cards
        self.index = 0
        self.last_card_id = None

    def card(self):
        return self.cards[self.index]

    def card_changed(self):
        changed = self.last_card_id != self.card().id
        self.last_card_id = self.card().id
        return changed

    def _on_prev_card(self):
        if self.index > 0:
            self.index -= 1
            self.render_card()

    def _on_next_card(self):
        if self.index + 1 < len(self.cards):
            self.index += 1
            self.render_card()

    def _should_enable_prev(self):
        return super()._should_enable_prev() or self.index > 0

    def _should_enable_next(self):
        return super()._should_enable_next() or self.index + 1 < len(self.cards)

    def _render_scheduled(self):
        super()._render_scheduled()
        self._updateButtons()


class EditDialog(QMainWindow):
    def __init__(self, note):
        super().__init__(None, Qt.WindowType.Window)
        self._closed = False
        self._closing = False
        self._close_callbacks = []
        self._request = 0
        self._previews = []
        self.form = aqt.forms.editcurrent.Ui_Dialog()
        self.form.setupUi(self)
        if hasattr(self.form, "buttonBox"):
            self.form.buttonBox.hide()
        self.setWindowTitle("Edit")
        self.setMinimumSize(250, 400)
        self.editor = aqt.editor.Editor(
            aqt.mw, self.form.fieldsArea, self,
            editor_mode=aqt.editor.EditorMode.EDIT_CURRENT,
        )
        toolbar = self.addToolBar("Note")
        toolbar.setMovable(False)

        def action(label, shortcut, callback):
            item = QAction(label, self)
            item.setShortcut(QKeySequence(shortcut))
            item.triggered.connect(callback)
            toolbar.addAction(item)
            return item

        action("Preview", "Ctrl+Shift+P", self.show_preview)
        action("Browse", "Ctrl+F", self.show_browser)
        self.previous_action = action("Previous", "Alt+Left", lambda: self.navigate(-1))
        self.next_action = action("Next", "Alt+Right", lambda: self.navigate(1))
        action("Close", "Escape", self.close)
        restoreGeom(self, DIALOG_TAG)
        _record(note.id)
        self._display(note)
        gui_hooks.operation_did_execute.append(self._operation)
        self.show()
        self.activateWindow()
        self.raise_()

    def _display(self, note):
        self.note = note
        cards = note.cards()
        self.editor.set_note(note)
        self.editor.card = cards[0] if cards else None
        ids = _prune_history()
        position = ids.index(note.id) if note.id in ids else -1
        self.previous_action.setEnabled(position > 0)
        self.next_action.setEnabled(0 <= position < len(ids) - 1)
        if any(card.queue == QUEUE_TYPE_SUSPENDED for card in cards):
            tooltip("Some of the cards associated with this note have been suspended", parent=self)

    def _switch(self, note_id, remember):
        self._request += 1
        request = self._request

        def saved():
            if self._closing or self._closed or request != self._request:
                return
            try:
                note = aqt.mw.col.get_note(note_id)
            except NotFoundError:
                self._refresh()
                return
            if remember:
                _record(note_id)
            self._display(note)

        self.editor.call_after_note_saved(saved)

    def reopen(self, note):
        self._switch(note.id, remember=True)

    def navigate(self, offset):
        ids = _prune_history()
        if self.note.id in ids:
            target = ids.index(self.note.id) + offset
            if 0 <= target < len(ids):
                self._switch(ids[target], remember=False)

    def _operation(self, changes, handler):
        if not self._closing and handler is not self.editor and (
            getattr(changes, "note_text", False) or getattr(changes, "note", False)
        ):
            self._refresh()

    def _refresh(self):
        ids = _prune_history()
        if not ids:
            self._finish_close()
            return
        nid = self.note.id if self.note.id in ids else ids[-1]
        self._display(aqt.mw.col.get_note(nid))

    def show_browser(self):
        def saved():
            if self._closing or self._closed:
                return
            browser = aqt.dialogs.open("Browser", aqt.mw)
            browser.table._state.sort_column = SEARCH_TAG
            browser.table._set_sort_indicator()
            browser.search_for(f"nid:{self.note.id}")
            browser.table.select_all()
            browser.search_for(SEARCH_TAG)

        self.editor.call_after_note_saved(saved)

    def show_preview(self):
        def saved():
            if self._closing or self._closed:
                return
            cards = aqt.mw.col.get_note(self.note.id).cards()
            if not cards:
                tooltip("No cards found", parent=self)
                return
            preview = NotePreviewer(cards, lambda: self._previews.remove(preview))
            self._previews.append(preview)
            preview.open()

        self.editor.call_after_note_saved(saved)

    def closeEvent(self, event):
        if self._closed:
            event.accept()
        else:
            event.ignore()
            self.closeWithCallback(lambda: None)

    def closeWithCallback(self, callback):
        if self._closed:
            callback()
            return
        self._close_callbacks.append(callback)
        if not self._closing:
            self._closing = True
            self.editor.call_after_note_saved(self._finish_close)

    def _finish_close(self):
        if self._closed:
            return
        self._closed = True
        gui_hooks.operation_did_execute.remove(self._operation)
        for preview in list(self._previews):
            preview.close()
        self.editor.cleanup()
        saveGeom(self, DIALOG_TAG)
        aqt.dialogs.markClosed(DIALOG_TAG)
        self.close()
        self.deleteLater()
        for callback in self._close_callbacks:
            callback()
        self._close_callbacks.clear()
