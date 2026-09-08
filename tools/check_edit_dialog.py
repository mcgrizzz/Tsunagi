"""Run with an aqt/PyQt environment; real Qt windows, simulated editor save callbacks."""
import importlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aqt  # noqa: E402
from anki.collection import Collection  # noqa: E402
from anki.lang import set_lang  # noqa: E402
from aqt import gui_hooks  # noqa: E402
from aqt.qt import QApplication  # noqa: E402

from tsunagi.http.compat import edit_dialog as dialog  # noqa: E402


class Hooks(list):
    def __call__(self, *args):
        for callback in list(self):
            callback(*args)


class Editor:
    def __init__(self, mw, area, parent, **kwargs):
        self.callbacks = []
        self.cleaned = 0
        self.pending_back = None

    def set_note(self, note):
        self.note = note

    def call_after_note_saved(self, callback):
        self.callbacks.append(callback)

    def flush(self):
        if self.pending_back is not None:
            self.note["Back"] = self.pending_back
            aqt.mw.col.update_note(self.note)
            self.pending_back = None
        callbacks, self.callbacks = self.callbacks, []
        for callback in callbacks:
            callback()

    def cleanup(self):
        self.cleaned += 1


def configure_module(module):
    module.restoreGeom = lambda *args: None
    module.saveGeom = lambda *args: None
    module.tooltip = lambda *args, **kwargs: None


def main():
    set_lang("en")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    gui_hooks.operation_did_execute = Hooks()
    gui_hooks.browser_will_search = Hooks()
    aqt.editor.Editor = Editor
    aqt.dialogs = aqt.DialogManager()
    aqt.dialogs._dialogs = {}
    configure_module(dialog)
    with tempfile.TemporaryDirectory() as directory:
        col = Collection(str(Path(directory, "collection.anki2")))
        aqt.mw = SimpleNamespace(col=col, app=app)
        try:
            notes = []
            for front in ("first", "second"):
                note = col.new_note(col.models.by_name("Basic"))
                note["Front"], note["Back"] = front, "original"
                col.add_note(note, col.decks.id("Default"))
                notes.append(note)
            window = dialog.open_editor(notes[0].id)
            app.processEvents()
            assert window.isVisible()
            assert window.note.id == notes[0].id
            assert len(gui_hooks.operation_did_execute) == 1
            window.editor.pending_back = "saved before switching"
            assert dialog.open_editor(notes[1].id) is window
            assert window.note.id == notes[0].id
            window.editor.flush()
            assert col.get_note(notes[0].id)["Back"] == "saved before switching"
            assert window.note.id == notes[1].id
            assert window.previous_action.isEnabled() and not window.next_action.isEnabled()
            window.navigate(-1)
            window.editor.flush()
            assert window.note.id == notes[0].id
            assert window.next_action.isEnabled()
            print("PASS: standalone window, reuse, saved switching and history.")

            # Simulate the addon's module purge/reimport while a window is open.
            importlib.reload(dialog)
            configure_module(dialog)
            assert dialog.open_editor(notes[1].id) is window
            window.editor.flush()
            assert len(gui_hooks.operation_did_execute) == 1
            assert len(gui_hooks.browser_will_search) == 1
            callbacks = []
            window.editor.pending_back = "saved before closing"
            window.closeWithCallback(lambda: callbacks.append(1))
            window.closeWithCallback(lambda: callbacks.append(2))
            assert window.editor.cleaned == 0
            window.editor.flush()
            assert col.get_note(notes[1].id)["Back"] == "saved before closing"
            assert callbacks == [1, 2]
            assert window.editor.cleaned == 1
            assert not gui_hooks.operation_did_execute
            assert aqt.dialogs._dialogs[dialog.DIALOG_TAG][1] is None
            print("PASS: reload reuses the window; close saves once and removes hooks.")

            window = dialog.open_editor(notes[1].id)
            assert isinstance(window, dialog.EditDialog)
            col.remove_notes([notes[1].id])
            gui_hooks.operation_did_execute(SimpleNamespace(note_text=True), None)
            assert window.note.id == notes[0].id
            col.remove_notes([notes[0].id])
            gui_hooks.operation_did_execute(SimpleNamespace(note_text=True), None)
            assert window.editor.cleaned == 1
            assert not gui_hooks.operation_did_execute
            assert aqt.dialogs._dialogs[dialog.DIALOG_TAG][1] is None
            print("PASS: deleted notes fall back through history, then close cleanly.")
        finally:
            app.processEvents()
            col.close()


if __name__ == "__main__":
    main()
