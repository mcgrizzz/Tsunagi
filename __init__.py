# __init__.py at the add-on ROOT (sibling of meta.json)

import sys
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
LIB = BASE / "lib"

if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

def _add_shared():
    p = LIB / "shared"
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

# call this early
_add_shared()

def _log_vendor_conflicts() -> None:
    """
    A module we vendor that is ALREADY imported from somewhere else (another
    addon's bundled copy, or Anki's own environment) keeps winning for the
    whole session - sys.modules beats sys.path, so our lib/shared pin never
    loads. That can't be fixed from here, but it CAN be the first line of a
    bug report instead of a mystery: say exactly which module and whose file.
    """
    try:
        shared = LIB / "shared"
        if not shared.is_dir():
            return
        prefix = str(shared)
        clashes = []
        for child in sorted(shared.iterdir()):
            name = child.name[:-3] if child.name.endswith(".py") else child.name
            if not name.isidentifier():
                continue
            mod = sys.modules.get(name)
            file = getattr(mod, "__file__", None) if mod is not None else None
            if file and not file.startswith(prefix):
                clashes.append(f"{name} ({file})")
        if clashes:
            print("[tsunagi] vendored modules already imported from elsewhere, "
                  "their versions win: " + "; ".join(clashes))
    except Exception:
        pass

# Catches copies loaded by addons that imported before us; runs again at
# profile open, when every addon has been imported, to catch the rest.
_log_vendor_conflicts()

try:
    from aqt import gui_hooks, mw
except ImportError:
    # Not running inside Anki (tests / tooling importing the addon root) - no-op.
    mw = None
else:
    def _on_profile_open() -> None:
        _log_vendor_conflicts()   # all addons are imported by now
        try:
            from .tsunagi.app import start_server
            start_server(mw)   # pass mw so app can read/write config via addonManager
        except Exception:
            print("[tsunagi] boot failed:\n" + traceback.format_exc())
        try:
            _start_dev_watch()
        except Exception:
            print("[tsunagi] dev watch failed:\n" + traceback.format_exc())
        try:
            from .tsunagi.adapters.dialogs import offer_ankiconnect_import
            offer_ankiconnect_import()   # one-time; no-op if AnkiConnect absent
        except Exception:
            print("[tsunagi] ankiconnect import offer failed:\n" + traceback.format_exc())

    def _on_profile_close() -> None:
        try:
            from .tsunagi.app import stop_server
            stop_server()
        except Exception:
            print("[tsunagi] shutdown failed:\n" + traceback.format_exc())

    # Start once a profile (and its collection) is open; stop before it closes
    # so the port is free for a restart or profile switch.
    gui_hooks.profile_did_open.append(_on_profile_open)
    gui_hooks.profile_will_close.append(_on_profile_close)

    # Event-stream feeders. Every callback body is fully wrapped: a raising
    # subscriber is REMOVED from the hook by Anki's generated code (and the
    # exception propagates into Anki), so one bad publish would otherwise
    # silence the stream for the whole session. Function-local imports keep
    # dispatch pointed at the live module across reload_addon()'s purge.
    def _on_op_executed(changes, handler=None) -> None:
        try:
            from .tsunagi.adapters.events import broker, dispatch_op
            # Nobody listening -> do nothing, not even the label fetch. The
            # editor fires one Update Note op per keystroke, so this runs hot.
            if not broker.has_subscribers():
                return
            # OpChanges carries flags but no identity; the undo label ("Update
            # Note", "Answer Card", ...) names the op that just completed and
            # is current by the time this hook fires.
            label = None
            try:
                if mw.col is not None:
                    label = mw.col.undo_status().undo or None
            except Exception:
                label = None
            dispatch_op(changes, handler, label=label)
        except Exception:
            pass

    def _on_card_answered(reviewer, card, ease) -> None:
        try:
            from .tsunagi.adapters.events import publish_review
            publish_review(card.id, ease)
        except Exception:
            pass

    def _on_sync_start() -> None:
        try:
            from .tsunagi.adapters.events import publish_sync
            publish_sync("started")
        except Exception:
            pass

    def _on_sync_finish() -> None:
        try:
            from .tsunagi.adapters.events import publish_sync
            publish_sync("finished")
        except Exception:
            pass

    # hasattr-guarded: hook availability on older Anki isn't verifiable from
    # here, and a missing hook should cost a feature, not the boot.
    for _hook_name, _callback in (
        ("operation_did_execute", _on_op_executed),
        ("reviewer_did_answer_card", _on_card_answered),
        ("sync_will_start", _on_sync_start),
        ("sync_did_finish", _on_sync_finish),
    ):
        if hasattr(gui_hooks, _hook_name):
            getattr(gui_hooks, _hook_name).append(_callback)

    def _open_settings():
        # Function-local import so reload_addon()'s module purge is enough to
        # pick up new dialog code - no re-registration needed.
        try:
            from .tsunagi.adapters.settings_dialog import open_settings
            open_settings(mw)
        except Exception:
            print("[tsunagi] settings dialog failed:\n" + traceback.format_exc())
            return False  # literal False: Anki falls back to the JSON editor

    # Registered at import time (not profile_did_open) so the dialog works
    # even when the server is disabled or failed to start. Returning None
    # from the config action suppresses Anki's raw JSON editor.
    mw.addonManager.setConfigAction(__name__, _open_settings)

    from aqt.qt import QAction
    _settings_action = QAction("Tsunagi Settings...", mw)
    _settings_action.triggered.connect(_open_settings)
    mw.form.menuTools.addAction(_settings_action)


_watch_timer = None
_watch_stamp = None
_watch_pending = None


def _source_stamp():
    """(file count, newest mtime) across our own modules - a cheap change signal."""
    newest = 0.0
    count = 0
    for path in (BASE / "tsunagi").rglob("*.py"):
        try:
            newest = max(newest, path.stat().st_mtime)
            count += 1
        except OSError:
            pass
    return count, newest


def _start_dev_watch() -> None:
    """
    Poll our source and reload when it settles. Off unless dev_watch_seconds
    is set; it exists so `tools/dev_sync.py` is the whole workflow, with no
    debug-console step afterwards.

    Runs on the Qt main thread, so a reload never races a request the way an
    HTTP-triggered one would - the handler would be executing on the very
    thread the reload has to join.
    """
    global _watch_timer, _watch_stamp, _watch_pending

    from .tsunagi.adapters.config import load_config
    seconds = float(load_config().get("dev_watch_seconds") or 0)
    if seconds <= 0 or _watch_timer is not None:
        return

    from aqt.qt import QTimer
    _watch_stamp = _source_stamp()

    def _tick() -> None:
        global _watch_stamp, _watch_pending
        stamp = _source_stamp()
        if stamp == _watch_stamp:
            _watch_pending = None
            return
        # Require one quiet tick before acting: dev_sync rewrites the whole
        # tree, and reloading mid-copy would import a half-written package.
        if stamp != _watch_pending:
            _watch_pending = stamp
            return
        _watch_stamp = stamp
        _watch_pending = None
        message = reload_addon()
        print(f"[tsunagi] dev watch: {message}")
        try:
            from aqt.utils import tooltip
            tooltip(f"Tsunagi: {message}", period=3000)
        except Exception:
            pass

    _watch_timer = QTimer(mw)
    _watch_timer.timeout.connect(_tick)
    _watch_timer.start(int(seconds * 1000))
    print(f"[tsunagi] dev watch active ({seconds}s)")


def reload_addon() -> str:
    """
    Dev helper: restart the HTTP server on the code currently on disk, without
    restarting Anki. From Anki's debug console (Ctrl+Shift+;):

        import tsunagi; tsunagi.reload_addon()

    Pair it with `python tools/dev_sync.py`, which copies the source into the
    installed add-on folder.

    Only this add-on's own package is purged. The vendored libraries in
    lib/shared stay loaded on purpose: re-importing pydantic mid-session would
    give every schema a new base class and break `isinstance` against models
    Anki already holds. Editing lib/ or this file still needs a restart.
    """
    import sys

    if mw is None:
        return "not running inside Anki"

    from .tsunagi.app import stop_server

    if not stop_server():
        return ("previous server thread is still alive, so the port is likely "
                "still held - restart Anki instead of reloading")

    pkg = __name__ + ".tsunagi"
    purged = [n for n in list(sys.modules) if n == pkg or n.startswith(pkg + ".")]
    for name in purged:
        del sys.modules[name]

    try:
        from .tsunagi.app import start_server
        start_server(mw)
    except Exception:
        return "reload failed:\n" + traceback.format_exc()

    from .tsunagi.app import server_url
    url = server_url()
    if url is None:
        return f"purged {len(purged)} modules but the server did not start - see the console"
    return f"reloaded {len(purged)} modules; listening on {url}"
