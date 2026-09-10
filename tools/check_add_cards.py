"""Check real Add Cards drafts and discard choices in an isolated Qt profile.

Run with aqt installed (validated with 26.8.1):
    python tools/check_add_cards.py --screenshot /tmp/tsunagi-add-cards.png

The Discard/Keep Editing buttons are clicked only in this disposable process.
"""

import base64
import sys
import traceback
from pathlib import Path

from qt_smoke import aqt, run, until, wait_for_editor


def check_add_cards(app, screenshot):
    from aqt.qt import QMessageBox, sip

    from tsunagi.adapters.anki import gui
    from tsunagi.http.compat.actions.gui import (
        GuiAddCardsParams,
        GuiAddNoteSetDataParams,
        ac_guiAddCards,
        ac_guiAddNoteSetData,
    )

    col = aqt.mw.col

    def wait(predicate):
        until(app, predicate)

    payload = {
        "deckName": "Default",
        "modelName": "Basic",
        "fields": {"Front": "Tsunagi Add Cards", "Back": "original"},
        "tags": ["qt"],
        "audio": {
            "filename": "qt-audio.mp3",
            "data": base64.b64encode(b"audio fixture").decode(),
            "fields": ["Back"],
        },
    }
    assert ac_guiAddCards(GuiAddCardsParams(note=payload)) == 0
    dialog = aqt.dialogs._dialogs["AddCards"][1]
    wait(lambda: dialog.isVisible())
    wait_for_editor(app, dialog.editor)

    def saved(window):
        done = []
        window.editor.call_after_note_saved(lambda: done.append(True))
        wait(lambda: bool(done))

    saved(dialog)
    assert dialog.editor.note["Front"] == "Tsunagi Add Cards"
    assert dialog.editor.note["Back"] == "original[sound:qt-audio.mp3]"
    assert (Path(col.media.dir()) / "qt-audio.mp3").read_bytes() == b"audio fixture"
    assert col.note_count() == 0
    print("PASS prefill, media and unsaved draft", flush=True)

    assert (
        ac_guiAddNoteSetData(
            GuiAddNoteSetDataParams(
                note={"fields": {"Front": " appended"}, "tags": ["appended"]},
                append=True,
            )
        )
        is True
    )
    saved(dialog)
    assert dialog.editor.note["Front"] == "Tsunagi Add Cards appended"
    assert set(dialog.editor.note.tags) == {"qt", "appended"}
    target = col.decks.id("Qt::Target")
    assert (
        ac_guiAddNoteSetData(
            GuiAddNoteSetDataParams(
                note={
                    "deckName": "Qt::Target",
                    "modelName": "Basic (and reversed card)",
                    "fields": {"Back": "replacement"},
                }
            )
        )
        is True
    )
    saved(dialog)
    assert dialog.editor.note.note_type()["name"] == "Basic (and reversed card)"
    assert dialog.editor.note["Back"] == "replacement"
    assert dialog.deck_chooser.selected_deck_id == target
    print("PASS append, tags, note type and deck chooser", flush=True)
    if screenshot:
        dialog.resize(900, 650)
        import time

        deadline = time.monotonic() + 1
        wait(lambda: time.monotonic() > deadline)
        assert dialog.grab().save(str(screenshot))

    replacement = {
        "deckName": "Default",
        "modelName": "Basic",
        "fields": {"Front": "replacement draft"},
    }
    assert ac_guiAddCards(GuiAddCardsParams(note=replacement)) == 0

    def discard_prompt():
        return next(
            (
                w
                for w in app.topLevelWidgets()
                if isinstance(w, QMessageBox)
                and w.isVisible()
                and w.button(QMessageBox.StandardButton.Discard)
            ),
            None,
        )

    wait(lambda: discard_prompt() is not None)
    prompt = discard_prompt()
    # First exercise Keep Editing: refill must not discard the current draft.
    keep = next(
        b
        for b in prompt.buttons()
        if prompt.buttonRole(b) == QMessageBox.ButtonRole.RejectRole
    )
    keep.click()
    wait(lambda: sip.isdeleted(prompt) or not prompt.isVisible())
    assert aqt.dialogs._dialogs["AddCards"][1] is dialog
    assert dialog.editor.note["Back"] == "replacement"
    assert ac_guiAddCards(GuiAddCardsParams(note=replacement)) == 0
    wait(lambda: discard_prompt() is not None)
    discard_prompt().button(QMessageBox.StandardButton.Discard).click()
    wait(
        lambda: (
            aqt.dialogs._dialogs["AddCards"][1] is not None
            and aqt.dialogs._dialogs["AddCards"][1] is not dialog
        )
    )
    reopened = aqt.dialogs._dialogs["AddCards"][1]
    wait_for_editor(app, reopened.editor)
    saved(reopened)
    assert reopened.editor.note["Front"] == "replacement draft"
    assert col.note_count() == 0
    print("PASS keep-editing and discard/reopen lifecycle", flush=True)
    reopened.add_current_note()
    wait(lambda: col.note_count() == 1 and reopened.editor.note["Front"] == "")
    added = col.get_note(col.find_notes("")[0])
    assert added["Front"] == "replacement draft"
    assert added.cards()[0].did == col.decks.id("Default")
    print("PASS explicit Add persists one note and clears the draft", flush=True)
    closed = []
    reopened.closeWithCallback(lambda: closed.append(True))
    wait(lambda: bool(closed))
    assert not gui.add_note_dialog_open()
    assert (
        ac_guiAddNoteSetData(GuiAddNoteSetDataParams(note=None))
        == gui.ADD_DIALOG_CLOSED
    )
    print("PASS clean close and closed-dialog response", flush=True)


if __name__ == "__main__":
    try:
        run(check_add_cards, __doc__)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
