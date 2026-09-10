"""Smoke-check the real Browser in an isolated, offscreen Anki profile.

Run with an environment containing aqt (validated with 26.8.1):
    python tools/check_browser.py --screenshot /tmp/tsunagi-browser.png

No installed add-ons, existing profiles, or AnkiConnect checkout are used.
This exercises Qt/editor readiness and adapter behavior, not OS window focus.
"""
import argparse
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
os.environ['ANKI_SOFTWAREOPENGL'] = '1'

import aqt  # noqa: E402
from aqt.profiles import ProfileManager  # noqa: E402
from aqt.qt import sip  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'lib' / 'shared'))
sys.path.insert(0, str(REPO))


def until(app, predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Qt condition timed out')


def check_browser(app, screenshot):
    from tsunagi.adapters.anki import gui

    col = aqt.mw.col
    note = col.new_note(col.models.by_name('Basic'))
    note['Front'], note['Back'] = 'Tsunagi real Qt browser', 'Disposable check'
    col.add_note(note, col.decks.id('Default'))
    cid = note.cards()[0].id
    assert gui.ac_browse() == []
    browser = aqt.dialogs._dialogs['Browser'][1]
    until(app, lambda: browser.isVisible() and browser.table.len() == 1)

    def editor_ready():
        result = []
        browser.editor.web.page().runJavaScript("typeof saveNow === 'function'", result.append)
        until(app, lambda: bool(result))
        return result[0]

    until(app, editor_ready)
    assert gui.ac_browse(f'cid:{cid}') == [cid]
    assert browser.form.searchEdit.lineEdit().text() == f'cid:{cid}'
    assert gui.ac_select_card(cid) is True
    until(app, lambda: gui.selected_notes() == [note.id])
    until(app, lambda: browser.editor.note is not None and browser.editor.note.id == note.id)
    print('PASS: real Browser search, selection and editor note.', flush=True)

    try:
        gui.ac_browse(123)
    except ValueError as exc:
        assert 'str' in str(exc)
    else:
        raise AssertionError('Qt accepted numeric search text')
    print('PASS: real QLineEdit rejects a numeric query.', flush=True)

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
    print('PASS: asynchronous Browser closure and closed-dialog selection.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='tsunagi-browser-qt-') as base:
        pm = ProfileManager(base)
        pm.setupMeta()
        pm.create('TsunagiQtAudit')
        pm.openProfile('TsunagiQtAudit')
        pm.meta['defaultLang'] = 'en_US'
        pm.save()
        pm.db.close()
        # Bypass IPC so this process cannot signal another Anki instance.
        aqt.AnkiApp.secondInstance = lambda self: False
        app = aqt._run(['anki', '-b', base, '-p', 'TsunagiQtAudit', '-l', 'en', '--safemode'], exec=False)
        assert app is not None
        errors = []
        original_hook = sys.excepthook

        def exception_hook(kind, value, tb):
            errors.append(str(value))
            traceback.print_exception(kind, value, tb)

        sys.excepthook = exception_hook
        try:
            until(app, lambda: aqt.mw.col is not None and aqt.mw.state == 'deckBrowser')
            check_browser(app, args.screenshot)
            assert not errors, errors
        finally:
            # Anki deletes the Qt wrapper during shutdown; don't inspect it after that.
            if not sip.isdeleted(aqt.mw):
                aqt.mw.close()
                until(app, lambda: sip.isdeleted(aqt.mw))
            sys.excepthook = original_hook
    assert not Path(base).exists()
    print('PASS: isolated Anki shutdown and temporary profile cleanup.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
