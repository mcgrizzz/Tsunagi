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

try:
    from aqt import gui_hooks, mw
except ImportError:
    # Not running inside Anki (tests / tooling importing the addon root) - no-op.
    mw = None
else:
    def _on_profile_open() -> None:
        try:
            from .tsunagi.app import start_server
            start_server(mw)   # pass mw so app can read/write config via addonManager
        except Exception:
            print("[tsunagi] boot failed:\n" + traceback.format_exc())
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
