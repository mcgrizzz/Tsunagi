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
