"""Screenshots of the settings page for config.md, in Anki's dark theme.

Opens the real page (AnkiWebView + pycmd bridge) in a disposable Anki profile
with tidy demo settings and a demo request log, and saves one PNG per page to
docs/images/settings-<page>.png. Needs the Qt interpreter (see
docs/development.md). Rerun after changing the settings page:

    QT_QPA_PLATFORM=offscreen python tools/settings_screenshots.py
"""
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch

from check_settings_dialog import js, open_page
from qt_smoke import aqt, run, until

from tsunagi.adapters import addon_actions, request_log
from tsunagi.adapters.config import ADDON_PACKAGE, _migrate

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
SIZE = (1000, 680)

DEMO = {
    "apps": [
        {"name": "Yomitan", "key": "yomitan-demo-key-0000000000000001", "role": "default"},
        {"name": "AnkiStats", "key": "ankistats-demo-key-00000000000002", "role": "read_only"},
        {"name": "Old script", "key": "old-demo-key-000000000000000000004", "role": "default",
         "enabled": False},
    ],
    "cors_allowlist": ["http://localhost", "https://app.asbplayer.dev"],
    "addon_enabled": {"fsrs_helper/easy_days": "undoable", "fsrs_helper/reschedule": "undoable"},
}


def demo_requests():
    now = time.time()
    rows = [
        (-42, "GET", "/v1/decks", None, "AnkiStats", None, 200),
        (-30, "POST", "/", "chrome-extension://likgccmbimhjbgkjambclfkhldnlhbnn", "Yomitan", "addNote", 200),
        (-29, "POST", "/", "chrome-extension://likgccmbimhjbgkjambclfkhldnlhbnn", "Yomitan", "canAddNotes", 200),
        (-20, "POST", "/", "https://app.asbplayer.dev", "No key, this computer", "addNote", 200),
        (-12, "POST", "/", "https://unknown.example", "No key, this computer", "requestPermission", 403),
        (-5, "POST", "/v1/notes", None, "Old script", None, 403),
    ]
    for dt, method, path, origin, app, action, status in rows:
        request_log.add({"time": now + dt, "method": method, "path": path, "origin": origin,
                         "local": True, "app": app, "action": action,
                         "error": "Old script is turned off; turn it on under Apps & keys in Tsunagi's settings"
                                  if app == "Old script" else None,
                         "status": status, "ms": 3.2})


def shoot(app, dlg, name):
    deadline = time.monotonic() + 0.5  # let the page repaint before grabbing
    while time.monotonic() < deadline:
        app.processEvents()
    dlg.grab().save(str(OUT / f"settings-{name}.png"))
    print(f"saved settings-{name}.png", flush=True)


def check(app, _screenshot):
    from aqt.theme import Theme

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = {**_migrate({})[0], **DEMO}
    manager = aqt.mw.addonManager
    real_get = manager.getConfig
    request_log.clear()
    demo_requests()
    aqt.mw.set_theme(Theme.DARK)
    with patch.object(manager, "getConfig",
                      lambda name: cfg if name == ADDON_PACKAGE else real_get(name)), \
         patch("tsunagi.app.server_url", lambda: "http://127.0.0.1:7777"), \
         patch.object(addon_actions, "unavailable", lambda provider: None):
        dlg = open_page(app)
        dlg.resize(*SIZE)
        until(app, lambda: "Server running" in js(app, dlg, "$('#server').textContent"))
        for page in ("server", "apps", "nokey", "web", "addons", "roles", "requests"):
            js(app, dlg, f"go('{page}')")
            if page == "requests":
                until(app, lambda: js(app, dlg, "document.querySelectorAll('tr.request').length > 0"))
            shoot(app, dlg, page)
        dlg.reject()
    request_log.clear()


if __name__ == "__main__":
    try:
        run(check, __doc__)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
