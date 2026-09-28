"""Drive the real settings page (AnkiWebView + pycmd bridge) in a disposable Anki profile.

Covers load, apps and no-key roles, the other-devices confirmation (Save going
to the field that needs it), a page's own revert and restore, role edit and
reset, add-on enabling and role grants, Save and Cancel keeping the window open,
the unsaved-changes prompt on X/Esc, and the AnkiConnect import-and-handover path. --screenshot PATH also saves images
(PATH-<name>.png), in light and dark themes.
"""
import socket
import sys
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch

from qt_smoke import aqt, run, until

from tsunagi.adapters import addon_actions, request_log, settings_dialog, settings_page
from tsunagi.adapters.config import ADDON_PACKAGE, _migrate
from tsunagi.adapters.dialogs import ANKICONNECT_ID

HELPERS = """
window.$ = (s) => document.querySelector(s);
// Events bubble, as real typing and selecting do.
window.setv = (s, v, ev) => { const e = $(s); e.value = v; e.dispatchEvent(new Event(ev || 'input', { bubbles: true })); };
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


def close(app, dlg):
    if js(app, dlg, "!$('#cancel').disabled"):
        js(app, dlg, "$('#cancel').click()")  # discards unsaved changes; stays open
        assert dlg.isVisible() and js(app, dlg, "$('#cancel').disabled && $('#save').disabled")
    dlg.reject()  # X/Esc: closes at once when nothing is unsaved
    until(app, lambda: not dlg.isVisible())


def save(app, dlg):
    js(app, dlg, "$('#save').click()")  # saves every page; stays open
    until(app, lambda: js(app, dlg, "$('#status').textContent === 'Saved'"))
    assert dlg.isVisible() and js(app, dlg, "$('#save').disabled && $('#cancel').disabled")
    close(app, dlg)


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
        assert js(app, dlg, "$('#restoreAll') === null")  # no global reset
        assert js(app, dlg, "$('#save').disabled && $('#cancel').disabled")  # nothing to save or discard
        until(app, lambda: js(app, dlg, "$('#server').textContent") == "Server off")  # not started here
        request_log.clear()
        now = time.time()
        request_log.add({"time": now - 5, "method": "GET", "path": "/v1/decks", "origin": None, "local": True,
                         "app": "Yomitan", "action": None, "error": None, "status": 200, "ms": 12.3})
        request_log.add({"time": now, "method": "POST", "path": "/", "origin": "https://spam.example", "local": True,
                         "app": "No key, this computer", "action": "requestPermission", "error": None,
                         "status": 403, "ms": 0.4})
        for page in ("server", "apps", "nokey", "web", "addons", "roles", "ankiconnect", "requests"):
            js(app, dlg, f"go('{page}')")
            assert js(app, dlg, "$('main h1') !== null")
            if page == "requests":
                until(app, lambda: js(app, dlg, "document.querySelectorAll('tr.request').length === 2"))
            if screenshot:
                shoot(app, dlg, screenshot, page)
        print("PASS: page loads and renders every page", flush=True)

        # Recent requests: one row per client, newest request first, failures
        # marked, nothing to save; filters narrow the list; Clear empties it.
        assert js(app, dlg, "document.querySelectorAll('tr.client').length === 2")
        assert "requestPermission" in js(app, dlg, "$('tr.request .what').textContent")
        assert js(app, dlg, "$('tr.request').classList.contains('failed')")
        assert js(app, dlg, "$('#save').disabled && $('[data-page=requests] .dot') === null")
        js(app, dlg, "$('tr.client[data-client=\"app:Yomitan\"] button.link').click()")
        until(app, lambda: js(app, dlg, "document.querySelectorAll('tr.request').length === 1"))
        assert js(app, dlg, "$('#requestClient').value") == "app:Yomitan"
        js(app, dlg, "$('#requestClient').value = ''; $('#requestClient').dispatchEvent(new Event('change'))")
        js(app, dlg, "$('#requestFailed').click()")
        until(app, lambda: js(app, dlg, "document.querySelectorAll('tr.request').length === 1 "
                                        "&& $('tr.request .what').textContent.includes('requestPermission')"))
        js(app, dlg, "$('#requestFailed').click(); $('#requestText').focus(); setv('#requestText', 'decks')")
        until(app, lambda: js(app, dlg, "document.querySelectorAll('tr.request').length === 1 "
                                        "&& $('tr.request .what').textContent === 'GET /v1/decks'"))
        js(app, dlg, "refreshRequests()")  # the 2 s refresh must not take the filter box's focus
        until(app, lambda: js(app, dlg, "document.activeElement.id") == "requestText")
        js(app, dlg, "setv('#requestText', 'nothing like this')")
        until(app, lambda: "match these filters" in js(app, dlg, "$('#requestsBody').textContent"))
        js(app, dlg, "setv('#requestText', '')")
        if screenshot:
            shoot(app, dlg, screenshot, "requests-filtered")
        js(app, dlg, "$('#clearRequests').click()")
        until(app, lambda: "No requests since Anki started" in js(app, dlg, "$('#requestsBody').textContent"))
        assert request_log.clients() == []
        print("PASS: recent requests per client, filters and clear", flush=True)

        # Typing in a field enables Save and Cancel and marks the page, and the
        # field keeps its focus; checkboxes too.
        js(app, dlg, "go('server'); $('#host').focus(); setv('#host', '127.0.0.2')")
        assert js(app, dlg, "!$('#save').disabled && !$('#cancel').disabled && $('[data-page=server] .dot') !== null")
        assert js(app, dlg, "document.activeElement.id") == "host"
        js(app, dlg, "setv('#host', '127.0.0.1')")
        assert js(app, dlg, "$('#save').disabled && $('[data-page=server] .dot') === null")
        js(app, dlg, "$('#enabled').click()")
        assert js(app, dlg, "!$('#save').disabled")
        js(app, dlg, "$('#enabled').click()")
        assert js(app, dlg, "$('#save').disabled")
        print("PASS: typing or ticking enables Save at once", flush=True)

        # An app with a new key in Read-only; keyless local requests closed.
        js(app, dlg, "go('apps'); $('#addApp').click()")
        until(app, lambda: js(app, dlg, "document.querySelectorAll('.app').length === 1"))
        assert js(app, dlg, "$('.app-detail .key') !== null")  # a new app opens with its key shown
        assert js(app, dlg, "!$('#save').disabled")
        assert "works once you save" in js(app, dlg, "$('#status').textContent")
        js(app, dlg, "$('.app button.disclosure').click()")
        assert js(app, dlg, "$('.app-detail') === null && $('.app button.disclosure').getAttribute('aria-expanded') === 'false'")
        js(app, dlg, "$('.app button.disclosure').click()")
        assert js(app, dlg, "$('.app-detail') !== null")
        js(app, dlg, "[...document.querySelectorAll('.app button.link')].find((b) => b.textContent === 'Copy').click()")
        assert js(app, dlg, "[...document.querySelectorAll('.app button.link')].some((b) => b.textContent === 'Copied')")
        js(app, dlg, "setv('.app .app-name', 'Phone'); setv('.app select', 'read_only', 'change')")
        assert js(app, dlg, "$('.app .app-on').checked")
        js(app, dlg, "$('.app .app-on').click()")
        assert js(app, dlg, "$('.app').classList.contains('off') && !$('.app .app-on').checked")
        if screenshot:
            shoot(app, dlg, screenshot, "apps-edited")
        js(app, dlg, "go('nokey'); setv('#no_key_local_role', 'none', 'change')")
        save(app, dlg)
        app_row = store["cfg"]["apps"][0]
        assert (app_row["name"], app_row["role"], len(app_row["key"])) == ("Phone", "read_only", 32)
        assert app_row["enabled"] is False
        assert store["cfg"]["no_key_local_role"] == "none"
        assert restarts == []
        print("PASS: apps (turned off) and no-key roles save", flush=True)

        # Other devices without a key need the confirmation box; the page's
        # own restore puts both sources back.
        dlg = open_page(app)
        js(app, dlg, "go('nokey'); setv('#no_key_remote_role', 'read_only', 'change')")
        if screenshot:
            shoot(app, dlg, screenshot, "nokey-confirm")
        # Save from another page: it stays open and goes to the field that needs attention.
        js(app, dlg, "go('server'); $('#save').click()")
        until(app, lambda: js(app, dlg, "!$('#errors').hidden"))
        assert "Confirm that other devices" in js(app, dlg, "$('#errors').textContent")
        assert dlg.isVisible() and store["cfg"]["no_key_remote_role"] == "none"
        assert js(app, dlg, "$('[data-page=nokey]').getAttribute('aria-current') === 'true'")
        assert js(app, dlg, "document.activeElement.id") == "confirmRemote"
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

        # Add-ons: approve on the Add-ons page; Default follows, destructive
        # actions only in Everything; withdrawing takes it out of every role.
        addon_actions.Registry().provide("check_addon", "Check Add-on", actions=[
            {"name": "apply", "title": "Apply it", "level": "normal", "run": print, "shows_ui": True},
            {"name": "later", "title": "Later", "level": "normal", "run": print},
            {"name": "wipe", "title": "Wipe history", "level": "destructive", "run": print},
            {"name": "peek", "title": "Peek", "level": "read", "run": print}])
        # Add-on text is not ours: long names and descriptions, several add-ons.
        long_text = ("Rebuilds every filtered deck in the collection, one after another, then re-sorts the "
                     "cards in each by the options that deck was created with. ") * 6
        addon_actions.Registry().provide("long_addon", "An Add-on With A Rather Long Name For Testing Layout",
                                         actions=[
            {"name": "rebuild", "level": "normal", "run": print, "description": long_text,
             "title": "Rebuild all filtered decks and re-sort them by their original search order options"},
            {"name": "purge", "title": "Purge", "level": "destructive", "run": print, "shows_ui": True,
             "description": "Deletes review history older than a year."},
            {"name": "stats", "title": "Statistics for every deck including subdecks and filtered decks",
             "level": "read", "run": print, "description": long_text}])
        addon_actions.Registry().provide("other_addon", "Other Add-on", actions=[
            {"name": "tidy", "title": "Tidy", "level": "normal", "run": print}])
        byid = "document.getElementById"
        try:
            dlg = open_page(app)
            js(app, dlg, "go('addons')")
            assert "Unavailable: FSRS Helper" in js(app, dlg, "$('[data-provider=fsrs_helper]').textContent")
            card = js(app, dlg, "$('[data-provider=check_addon]').textContent")
            assert "0 of 3 enabled" in card and "Can run it" not in card
            if screenshot:
                shoot(app, dlg, screenshot, "addons-disabled")
            js(app, dlg, "$('[data-approve-all=check_addon]').click()")
            assert js(app, dlg, f"{byid}('approve_check_addon__wipe').checked") is False
            js(app, dlg, f"{byid}('approve_check_addon__wipe').click()")
            text = js(app, dlg, "$('[data-provider=check_addon]').textContent")
            assert "3 of 3 enabled" in text
            # Reads are always enabled: checked and locked.
            assert js(app, dlg, f"{byid}('approve_check_addon__peek').checked && {byid}('approve_check_addon__peek').disabled")
            # Long descriptions start folded, with a visible control for the full text.
            long_row = "document.querySelector('[data-provider=long_addon] .action-desc')"
            assert js(app, dlg, f"{long_row}.querySelector('.folded') !== null")
            if screenshot:
                js(app, dlg, "$('[data-provider=long_addon]').scrollIntoView()")
                shoot(app, dlg, screenshot, "addons-long")
            js(app, dlg, f"{long_row}.querySelector('button.fold').click()")
            assert js(app, dlg, f"{long_row}.querySelector('.folded') === null")
            if screenshot:
                js(app, dlg, "$('[data-provider=long_addon]').scrollIntoView()")
                shoot(app, dlg, screenshot, "addons-long-open")
            js(app, dlg, "$('main').scrollTop = 0")
            if screenshot:
                shoot(app, dlg, screenshot, "addons")
            js(app, dlg, "go('roles'); $('[data-edit=default]').click(); $('[data-area=addon]').click()")
            assert js(app, dlg, f"{byid}('perm_addon:check_addon/apply').checked") is True
            assert js(app, dlg, f"{byid}('perm_addon:check_addon/wipe').checked") is False
            # Allowing every enabled action by name shows a full check, but it is not
            # the whole area: actions enabled later are not allowed by it.
            js(app, dlg, f"{byid}('perm_addon:check_addon/wipe').click()")
            assert js(app, dlg, "$('#area_addon').checked && !$('#area_addon').indeterminate")
            assert js(app, dlg, "draft.roles.find((r) => r.id === 'default').grants.includes('addon')") is False
            js(app, dlg, f"{byid}('perm_addon:check_addon/wipe').click()")
            assert js(app, dlg, "$('#area_addon').indeterminate")
            assert js(app, dlg, "$('#resetRole') === null")  # approving left Default at its defaults
            if screenshot:
                js(app, dlg, "$('[data-area=addon]').scrollIntoView()")
                shoot(app, dlg, screenshot, "role-addons")
            save(app, dlg)
            assert store["cfg"]["addon_enabled"] == {"check_addon/apply": "normal", "check_addon/later": "normal",
                                                      "check_addon/wipe": "destructive"}
            assert store["cfg"]["roles"] == {}
            dlg = open_page(app)
            js(app, dlg, f"go('addons'); {byid}('approve_check_addon__later').click()")
            js(app, dlg, "go('roles'); $('[data-edit=default]').click(); $('[data-area=addon]').click()")
            assert js(app, dlg, f"{byid}('perm_addon:check_addon/later').disabled") is True
            assert "Disabled" in js(app, dlg, f"{byid}('row_perm_addon:check_addon/later').textContent")
            js(app, dlg, "go('addons'); $('#revertPage').click()")
            assert js(app, dlg, f"{byid}('approve_check_addon__later').checked") is True
            js(app, dlg, "go('roles')")
            assert "Built-in, edited" not in js(app, dlg, "$('[data-role=default]').textContent")
            close(app, dlg)
        finally:
            for pid in ("check_addon", "long_addon", "other_addon"):
                addon_actions.PROVIDERS.pop(pid, None)
        print("PASS: add-on approvals, Default's grants and revert", flush=True)

        # X / Esc: closes at once when clean; with unsaved changes it asks
        # Save / Discard / Keep editing.
        before = dict(store["cfg"])
        dlg = open_page(app)
        dlg.reject()
        until(app, lambda: not dlg.isVisible())
        dlg = open_page(app)
        js(app, dlg, "go('nokey'); setv('#no_key_local_role', 'default', 'change')")
        until(app, lambda: dlg.tsunagi_bridge.dirty)
        dlg.reject()
        until(app, lambda: js(app, dlg, "$('.dialog') !== null"))
        assert dlg.isVisible() and "Requests without a key" in js(app, dlg, "$('.dialog').textContent")
        if screenshot:
            shoot(app, dlg, screenshot, "close-prompt")
        js(app, dlg, "$('#keepEditing').click()")
        assert js(app, dlg, "$('.dialog') === null") and dlg.isVisible()
        dlg.reject()
        until(app, lambda: js(app, dlg, "$('.dialog') !== null"))
        js(app, dlg, "$('#discardClose').click()")
        until(app, lambda: not dlg.isVisible())
        assert store["cfg"] == before
        dlg = open_page(app)
        js(app, dlg, "go('nokey'); setv('#no_key_local_role', 'default', 'change')")
        until(app, lambda: dlg.tsunagi_bridge.dirty)
        dlg.reject()
        until(app, lambda: js(app, dlg, "$('.dialog') !== null"))
        js(app, dlg, "$('#saveClose').click()")
        until(app, lambda: not dlg.isVisible())
        assert store["cfg"]["no_key_local_role"] == "default"
        print("PASS: X/Esc closes when clean, asks Save / Discard / Keep editing when not", flush=True)

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
                until(app, lambda: restarts)
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
            with patch("tsunagi.app.server_url", lambda: "http://127.0.0.1:7777"):
                dlg = open_page(app)
                until(app, lambda: js(app, dlg, "$('#server').textContent") == "Server running on 127.0.0.1:7777")
                shoot(app, dlg, screenshot, "dark-running")
                close(app, dlg)
            dlg = open_page(app)
            for page in ("apps", "addons", "roles"):
                js(app, dlg, f"go('{page}')")
                shoot(app, dlg, screenshot, "dark-" + page)
            close(app, dlg)


if __name__ == "__main__":
    try:
        run(check, __doc__)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
