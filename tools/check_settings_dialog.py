"""Drive the real settings page (AnkiWebView + pycmd bridge) in a disposable Anki profile.

Covers load, apps and no-key roles, the other-devices confirmation, a page's own
restore, role edit and reset, the confirmed global restore, cancel, and the
AnkiConnect import-and-handover path. --screenshot PATH also saves images
(PATH-<name>.png), in light and dark themes.
"""
import socket
import sys
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch

from qt_smoke import aqt, run, until

from tsunagi.adapters import settings_dialog, settings_page
from tsunagi.adapters.config import ADDON_PACKAGE, _migrate
from tsunagi.adapters.dialogs import ANKICONNECT_ID

HELPERS = """
window.$ = (s) => document.querySelector(s);
window.setv = (s, v, ev) => { const e = $(s); e.value = v; e.dispatchEvent(new Event(ev || 'input')); };
window.go = (id) => $('[data-page=' + id + ']').click();
"""


class ProbeServer:
    """A disposable listener with the shutdown interface used by AnkiConnect."""

    def __init__(self):
        self.port = 0
        self.sock = None
        self.listen()

    def listen(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", self.port))
        self.port = self.sock.getsockname()[1]
        self.sock.listen()

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None


def js(app, dlg, code):
    out = []
    dlg.tsunagi_web.page().runJavaScript(HELPERS + code, out.append)
    until(app, lambda: out)
    return out[0]


def open_page(app):
    dlg = settings_page.make_dialog(aqt.mw)
    dlg.show()
    until(app, lambda: js(app, dlg, "window.tsunagiReady === true"))
    return dlg


def shoot(app, dlg, path, name):
    deadline = time.monotonic() + 0.4  # let the page repaint before grabbing
    while time.monotonic() < deadline:
        app.processEvents()
    dlg.grab().save(str(path.with_name(f"{path.stem}-{name}.png")))


def save(app, dlg):
    js(app, dlg, "$('#save').click()")
    until(app, lambda: not dlg.isVisible())


def check(app, screenshot):
    store = {"cfg": _migrate({})[0]}
    manager = aqt.mw.addonManager
    real_get = manager.getConfig
    restarts = []
    with patch.object(manager, "getConfig",
                      lambda name: store["cfg"] if name == ADDON_PACKAGE else real_get(name)), \
         patch.object(manager, "writeConfig",
                      lambda name, cfg: store.update(cfg=dict(cfg)) if name == ADDON_PACKAGE else None), \
         patch.object(settings_dialog, "_restart_server",
                      lambda mw, enabled: restarts.append(enabled)):
        # Load and render every page.
        dlg = open_page(app)
        assert js(app, dlg, "$('#version').textContent").startswith("Tsunagi ")
        assert js(app, dlg, "$('footer #restoreAll') === null && $('#nav #restoreAll') !== null")
        for page in ("server", "apps", "nokey", "web", "roles", "ankiconnect"):
            js(app, dlg, f"go('{page}')")
            assert js(app, dlg, "$('main h1') !== null")
            if screenshot:
                shoot(app, dlg, screenshot, page)
        print("PASS: page loads and renders every page", flush=True)

        # An app with a new key in Read-only; keyless local requests closed.
        js(app, dlg, "go('apps'); $('#addApp').click()")
        until(app, lambda: js(app, dlg, "document.querySelectorAll('.app').length === 1"))
        assert js(app, dlg, "$('.app-detail .key') !== null")  # a new app opens with its key shown
        assert "copied" in js(app, dlg, "$('#status').textContent")
        js(app, dlg, "[...document.querySelectorAll('.app button.link')].find((b) => b.textContent === 'Copy').click()")
        assert js(app, dlg, "[...document.querySelectorAll('.app button.link')].some((b) => b.textContent === 'Copied')")
        js(app, dlg, "setv('.app .app-name', 'Phone'); setv('.app select', 'read_only', 'change')")
        if screenshot:
            shoot(app, dlg, screenshot, "apps-edited")
        js(app, dlg, "go('nokey'); setv('#no_key_local_role', 'none', 'change')")
        save(app, dlg)
        app_row = store["cfg"]["apps"][0]
        assert (app_row["name"], app_row["role"], len(app_row["key"])) == ("Phone", "read_only", 32)
        assert store["cfg"]["no_key_local_role"] == "none"
        assert restarts == []
        print("PASS: apps and no-key roles save", flush=True)

        # Other devices without a key need the confirmation box; the page's
        # own restore puts both sources back.
        dlg = open_page(app)
        js(app, dlg, "go('nokey'); setv('#no_key_remote_role', 'read_only', 'change')")
        if screenshot:
            shoot(app, dlg, screenshot, "nokey-confirm")
        js(app, dlg, "$('#save').click()")
        until(app, lambda: js(app, dlg, "!$('#errors').hidden"))
        assert "Confirm that other devices" in js(app, dlg, "$('#errors').textContent")
        assert dlg.isVisible() and store["cfg"]["no_key_remote_role"] == "none"
        assert js(app, dlg, "$('[data-page=nokey] .dot') !== null && $('#revertPage') !== null")
        js(app, dlg, "go('server'); setv('#host', '0.0.0.0'); go('nokey'); $('#revertPage').click()")
        # Revert brings back this page's saved values only; the Server edit stays.
        assert js(app, dlg, "[$('#no_key_local_role').value, $('#no_key_remote_role').value].join()") == "none,none"
        assert js(app, dlg, "$('#revertPage') === null && $('[data-page=server] .dot') !== null")
        js(app, dlg, "$('#restorePage').click()")
        assert js(app, dlg, "[$('#no_key_local_role').value, $('#no_key_remote_role').value].join()") == "default,none"
        js(app, dlg, "go('server'); $('#revertPage').click(); go('nokey')")
        js(app, dlg, "setv('#no_key_local_role', 'none', 'change'); setv('#no_key_remote_role', 'read_only', 'change');"
                     "$('#confirmRemote').click()")
        save(app, dlg)
        assert store["cfg"]["no_key_remote_role"] == "read_only"
        assert store["cfg"]["host"] == "127.0.0.1"
        print("PASS: other devices need confirmation; page revert and restore", flush=True)

        # Roles: the list shows usage; edit a built-in role, then reset it.
        dlg = open_page(app)
        js(app, dlg, "go('roles')")
        assert "Phone" in js(app, dlg, "$('[data-role=read_only]').textContent")
        js(app, dlg, "$('[data-edit=default]').click(); $('#area_manage').click(); $('[data-area=read]').click()")
        if screenshot:
            shoot(app, dlg, screenshot, "role-editor")
        save(app, dlg)
        assert "manage" not in store["cfg"]["roles"]["default"]["grants"]
        dlg = open_page(app)
        js(app, dlg, "go('roles'); $('[data-edit=default]').click()")
        assert js(app, dlg, "$('#resetRole').disabled") is False
        js(app, dlg, "$('#resetRole').click()")
        save(app, dlg)
        assert store["cfg"]["roles"] == {}
        print("PASS: role edit and reset", flush=True)

        # Restore all defaults asks first; Cancel then changes nothing.
        before = dict(store["cfg"])
        dlg = open_page(app)
        js(app, dlg, "$('#restoreAll').click()")
        assert "Remove 1 app" in js(app, dlg, "$('.dialog').textContent")
        if screenshot:
            shoot(app, dlg, screenshot, "restore-all")
        js(app, dlg, "$('#confirmRestoreAll').click()")
        until(app, lambda: js(app, dlg, "go('apps'); $('.app') === null && $('.dialog') === null"))
        js(app, dlg, "$('#cancel').click()")
        until(app, lambda: not dlg.isVisible())
        assert store["cfg"] == before
        print("PASS: restore all defaults confirms; cancel keeps settings", flush=True)

        # AnkiConnect import: stage, save, hand the port over.
        server, timer = ProbeServer(), aqt.qt.QTimer()
        timer.start(60_000)
        sys.modules[ANKICONNECT_ID] = SimpleNamespace(ac=SimpleNamespace(server=server, timer=timer))
        toggled = []
        ac_cfg = {"apiKey": "from-ankiconnect", "webBindPort": server.port,
                  "webCorsOriginList": ["http://imported"]}
        try:
            with patch.object(manager, "allAddons", lambda: [ANKICONNECT_ID]), \
                 patch.object(manager, "addon_meta", lambda name: SimpleNamespace(enabled=True)), \
                 patch.object(manager, "toggleEnabled", lambda name, enable: toggled.append(enable)), \
                 patch.object(manager, "getConfig",
                              lambda name: store["cfg"] if name == ADDON_PACKAGE else ac_cfg):
                dlg = open_page(app)
                js(app, dlg, "go('ankiconnect'); $('#importAnkiConnect').click()")
                until(app, lambda: js(app, dlg, "$('#pendingImport') !== null"))
                assert str(server.port) in js(app, dlg, "$('#pendingImport').textContent")
                save(app, dlg)
        finally:
            sys.modules.pop(ANKICONNECT_ID, None)
            timer.stop()
        cfg = store["cfg"]
        assert cfg["port"] == server.port and cfg["prefer_port"] == server.port
        assert {"name": "AnkiConnect key", "key": "from-ankiconnect", "role": "default"} in cfg["apps"]
        assert "http://imported" in cfg["cors_allowlist"] and cfg["ankiconnect_imported_at"]
        assert toggled == [False] and server.sock is None and restarts == [True]
        server.close()
        print("PASS: AnkiConnect import hands over its port", flush=True)

        if screenshot:
            from aqt.theme import Theme

            aqt.mw.set_theme(Theme.DARK)
            dlg = open_page(app)
            for page in ("apps", "roles"):
                js(app, dlg, f"go('{page}')")
                shoot(app, dlg, screenshot, "dark-" + page)
            js(app, dlg, "$('#cancel').click()")
            until(app, lambda: not dlg.isVisible())


if __name__ == "__main__":
    try:
        run(check, __doc__)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
