"""Search a cold Browser immediately, using an isolated real Qt profile."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from qt_smoke import aqt, run, until, wait_for_editor


def check(app, screenshot):
    from aqt.operations import QueryOp
    from aqt.webview import AnkiWebPage

    from tsunagi.adapters.anki import gui

    col = aqt.mw.col
    notes = []
    for front in ("cold browser target", "cold browser other"):
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = front
        col.add_note(note, col.decks.id("Default"))
        notes.append(note)
    cid = notes[0].cards()[0].id
    assert aqt.dialogs._dialogs["Browser"][1] is None
    errors = []
    console = AnkiWebPage.javaScriptConsoleMessage

    def record_console(page, level, message, line, source):
        if "saveNow is not defined" in message:
            errors.append(message)
        return console(page, level, message, line, source)

    with patch.object(AnkiWebPage, "javaScriptConsoleMessage", record_console):
        # The API request itself must open and search the Browser. Do not warm it
        # up or wait for WebEngine before this call: that masked the original race.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(gui.ac_browse, f"cid:{cid}")
            until(app, future.done)
            assert future.result() == [cid]
        browser = aqt.dialogs._dialogs["Browser"][1]
        until(app, lambda: browser.isVisible() and browser.table.len() == 1)
        wait_for_editor(app, browser.editor)
    assert not errors, errors
    assert browser.form.searchEdit.lineEdit().text() == f"cid:{cid}"
    assert gui.ac_select_card(cid) is True
    until(app, lambda: browser.editor.note is not None and browser.editor.note.id == notes[0].id)
    assert gui.selected_notes() == [notes[0].id]
    print("PASS: cold API search filters two cards to the requested card and selects its note.", flush=True)
    closed = []
    browser.closeWithCallback(lambda: closed.append(True))
    until(app, lambda: bool(closed))
    # Browser close can return before its editor-save operation's UI callback.
    # Queue a read behind it so the collection stays open until that work settles.
    settled = []
    QueryOp(parent=aqt.mw, op=lambda col: None, success=lambda _: settled.append(True)).run_in_background()
    until(app, lambda: bool(settled))


if __name__ == "__main__":
    run(check, __doc__)
