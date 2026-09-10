"""Isolated real-Anki setup for focused GUI smoke tools."""

import argparse
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ["ANKI_SOFTWAREOPENGL"] = "1"

import aqt  # noqa: E402
from aqt.profiles import ProfileManager  # noqa: E402
from aqt.qt import QCoreApplication, QEvent, sip  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib" / "shared"))
sys.path.insert(0, str(REPO))


def until(app, predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Qt condition timed out")


def wait_for_editor(app, editor):
    """Wait for the editor's asynchronous JavaScript save bridge."""

    def ready():
        result = []
        editor.web.page().runJavaScript("typeof saveNow === 'function'", result.append)
        until(app, lambda: bool(result))
        return result[0]

    until(app, ready)


def run(check, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tsunagi-smoke-qt-") as base:
        pm = ProfileManager(base)
        pm.setupMeta()
        pm.create("TsunagiQtAudit")
        pm.openProfile("TsunagiQtAudit")
        pm.meta["defaultLang"] = "en_US"
        pm.save()
        pm.db.close()
        # Bypass IPC so this process cannot signal another Anki instance.
        aqt.AnkiApp.secondInstance = lambda self: False
        app = aqt._run(
            ["anki", "-b", base, "-p", "TsunagiQtAudit", "-l", "en", "--safemode"],
            exec=False,
        )
        assert app is not None
        errors = []
        original_hook = sys.excepthook

        def exception_hook(kind, value, tb):
            errors.append(str(value))
            traceback.print_exception(kind, value, tb)

        sys.excepthook = exception_hook
        try:
            until(app, lambda: aqt.mw.col is not None and aqt.mw.state == "deckBrowser")
            check(app, args.screenshot)
            assert not errors, errors
        finally:
            # Anki deletes the Qt wrapper during shutdown; don't inspect it after that.
            if not sip.isdeleted(aqt.mw):
                aqt.mw.close()
                until(app, lambda: sip.isdeleted(aqt.mw))
            sys.excepthook = original_hook
    assert not Path(base).exists()
    print("PASS: isolated Anki shutdown and temporary profile cleanup.", flush=True)
