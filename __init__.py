# __init__.py at the add-on ROOT (sibling of meta.json)

import importlib
import sys, os
from pathlib import Path
import anki  # for is_win / is_mac / is_lin
from aqt import mw
from aqt.qt import QTimer

BASE = Path(__file__).resolve().parent
LIB = BASE / "lib"

_ts_started = False

if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

def _add_shared():
    p = LIB / "shared"
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

def _attach_pydantic_core():
    try:
        from packaging import tags  # vendored in lib/shared
    except Exception:
        return

    if anki.utils.is_win: # type: ignore
        os_dir = "win"
    elif anki.utils.is_mac: # type: ignore
        os_dir = "macos"
    elif anki.utils.is_lin: # type: ignore
        os_dir = "linux"
    else:
        return

    root = LIB / os_dir / "pydantic_core"
    if not root.exists():
        return

    chosen = None
    for t in tags.sys_tags():  # best-match first for this interpreter
        cand = root / t.interpreter / t.platform                 # e.g. cp311/win_amd64
        # we need the directory that CONTAINS the 'pydantic_core' pkg
        if (cand / "pydantic_core").exists() and list((cand / "pydantic_core").glob("_pydantic_core*.*")):
            chosen = cand
            break

    if chosen and str(chosen) not in sys.path:
        sys.path.insert(0, str(chosen))

# call these early
_add_shared()
_attach_pydantic_core()

# --- Start server exactly once ---
def _boot():
    global _ts_started
    if _ts_started:
        return
    try:
        from .tsunagi.app import start_server
        start_server(mw)   # pass mw so app can read/write config via addonManager
        _ts_started = True
    except Exception as e:
        print("[tsunagi] boot failed:", e)

QTimer.singleShot(1200, _boot)
