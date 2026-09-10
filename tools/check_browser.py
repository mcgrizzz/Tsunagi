"""Smoke-check the real Browser in an isolated, offscreen Anki profile.

Run with an environment containing aqt (validated with 26.8.1):
    python tools/check_browser.py --screenshot /tmp/tsunagi-browser.png

No installed add-ons, existing profiles, or AnkiConnect checkout are used.
This exercises Qt/editor readiness and adapter behavior, not OS window focus.
"""

import sys
import time
import traceback

from qt_smoke import aqt, run, until, wait_for_editor


def check_browser(app, screenshot):
    from tsunagi.adapters.anki import gui

    col = aqt.mw.col
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"], note["Back"] = "Tsunagi real Qt browser", "Disposable check"
    col.add_note(note, col.decks.id("Default"))
    cid = note.cards()[0].id
    assert gui.ac_browse() == []
    browser = aqt.dialogs._dialogs["Browser"][1]
    until(app, lambda: browser.isVisible() and browser.table.len() == 1)

    wait_for_editor(app, browser.editor)
    assert gui.ac_browse(f"cid:{cid}") == [cid]
    assert browser.form.searchEdit.lineEdit().text() == f"cid:{cid}"
    assert gui.ac_select_card(cid) is True
    until(app, lambda: gui.selected_notes() == [note.id])
    until(
        app,
        lambda: browser.editor.note is not None and browser.editor.note.id == note.id,
    )
    print("PASS: real Browser search, selection and editor note.", flush=True)

    try:
        gui.ac_browse(123)
    except ValueError as exc:
        assert "str" in str(exc)
    else:
        raise AssertionError("Qt accepted numeric search text")
    print("PASS: real QLineEdit rejects a numeric query.", flush=True)

    if screenshot:
        browser.resize(1100, 800)
        paint_deadline = time.monotonic() + 1
        until(app, lambda: time.monotonic() > paint_deadline)
        assert browser.grab().save(str(screenshot))

    closed = []
    browser.closeWithCallback(lambda: closed.append(True))
    until(app, lambda: bool(closed))
    assert gui.ac_select_card(cid) is False
    assert gui.selected_notes() == []
    print("PASS: asynchronous Browser closure and closed-dialog selection.", flush=True)


if __name__ == "__main__":
    try:
        run(check_browser, __doc__)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
