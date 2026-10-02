"""The settings page's Python side: page state, draft -> config, and the bridge."""
import json
from types import SimpleNamespace

import pytest

from tsunagi.adapters import settings_page as page
from tsunagi.adapters.config import DEFAULTS, _migrate
from tsunagi.shared.permissions import PERMISSIONS, PUBLIC


def fresh():
    return _migrate({})[0]


def draft_of(cfg):
    """What the page sends back when nothing was edited."""
    return page.page_draft(page.page_state(cfg, {}))


def test_catalog_labels_every_permission():
    catalog = page.permission_catalog()
    listed = {a["area"] for a in catalog} | {n["name"] for a in catalog for n in a["names"]}
    assert {p for p in PERMISSIONS if p != PUBLIC} <= listed
    assert all(n["label"] for a in catalog for n in a["names"])


def test_untouched_draft_saves_the_same_config():
    cfg = fresh()
    new_cfg, restart, errors = page.config_from_page(cfg, draft_of(cfg))
    assert (new_cfg, restart, errors) == (cfg, False, [])


def test_apps_rows_and_roles_are_saved():
    cfg = fresh()
    draft = draft_of(cfg)
    draft["apps"] = [{"name": " Yomitan ", "key": "k" * 32, "role": "read_only"}]
    draft["no_key_local_role"] = "none"
    draft["roles"].append({"id": "custom_1", "name": "Tagger", "grants": ["read", "write:tags"]})
    new_cfg, restart, errors = page.config_from_page(cfg, draft)
    assert errors == [] and restart is False
    assert new_cfg["apps"] == [{"name": "Yomitan", "key": "k" * 32, "role": "read_only"}]
    assert new_cfg["no_key_local_role"] == "none"
    assert new_cfg["roles"] == {"custom_1": {"name": "Tagger", "grants": ["read", "write:tags"]}}


def test_turning_an_app_off_is_saved_and_shown():
    cfg = fresh()
    draft = draft_of(cfg)
    draft["apps"] = [{"name": "On", "key": "a" * 32, "role": "default", "enabled": True},
                     {"name": "Off", "key": "b" * 32, "role": "read_only", "enabled": False}]
    new_cfg, _, errors = page.config_from_page(cfg, draft)
    assert errors == []
    assert new_cfg["apps"] == [{"name": "On", "key": "a" * 32, "role": "default"},
                               {"name": "Off", "key": "b" * 32, "role": "read_only", "enabled": False}]
    assert [a["enabled"] for a in page.page_state(new_cfg, {})["apps"]] == [True, False]


def test_only_edited_built_ins_are_stored_and_reset_removes_them():
    cfg = fresh()
    draft = draft_of(cfg)
    default = next(g for g in draft["roles"] if g["id"] == "default")
    default["grants"] = [g for g in default["grants"] if g != "manage"]
    edited, _, _ = page.config_from_page(cfg, draft)
    assert edited["roles"]["default"]["grants"] == sorted(
        {"read", "write", "gui", "sync", "events:changes"})
    state = page.page_state(edited, {})
    row = next(g for g in state["roles"] if g["id"] == "default")
    assert row["default"]["grants"] != row["grants"]  # the page offers Reset
    reset, _, _ = page.config_from_page(edited, draft_of(cfg))
    assert reset["roles"] == {}


def test_add_on_grants_survive_an_unrelated_save():
    cfg = fresh()
    cfg["addon_enabled"] = {"fsrs_helper/easy_days": "undoable"}
    cfg["roles"] = {"phone": {"name": "Phone", "grants": ["addon:fsrs_helper/easy_days", "read"]}}
    new_cfg, _, errors = page.config_from_page(cfg, draft_of(cfg))
    assert errors == [] and new_cfg == cfg


def test_default_shows_its_approved_add_on_actions_and_keeps_them_when_edited():
    cfg = fresh()
    cfg["addon_enabled"] = {"fsrs_helper/easy_days": "undoable", "fsrs_helper/wipe": "destructive"}
    state = page.page_state(cfg, {})
    row = next(g for g in state["roles"] if g["id"] == "default")
    assert "addon:fsrs_helper/easy_days" in row["grants"]
    assert "addon:fsrs_helper/wipe" not in row["grants"]
    # The page adds its draft's approvals to this itself (settings.js defaultOf).
    assert not any(g.startswith("addon:") for g in row["default"]["grants"])
    assert state["addon_enabled"] == cfg["addon_enabled"]
    draft = draft_of(cfg)
    default = next(g for g in draft["roles"] if g["id"] == "default")
    default["grants"] = [g for g in default["grants"] if g != "manage"]
    edited, _, _ = page.config_from_page(cfg, draft)
    assert "addon:fsrs_helper/easy_days" in edited["roles"]["default"]["grants"]


def test_approvals_are_saved_and_default_stays_unedited():
    cfg = fresh()
    draft = draft_of(cfg)
    draft["addon_enabled"] = {"fsrs_helper/easy_days": "undoable"}
    default = next(g for g in draft["roles"] if g["id"] == "default")
    default["grants"].append("addon:fsrs_helper/easy_days")  # what approving does on the page
    new_cfg, _, errors = page.config_from_page(cfg, draft)
    assert errors == []
    assert new_cfg["addon_enabled"] == {"fsrs_helper/easy_days": "undoable"}
    assert new_cfg["roles"] == {}  # Default is still at its defaults


@pytest.mark.parametrize("approvals", [{"fsrs_helper/easy_days": "read"}, {"no slash": "undoable"}])
def test_invalid_approvals_are_refused(approvals):
    cfg = fresh()
    draft = draft_of(cfg)
    draft["addon_enabled"] = approvals
    _, _, errors = page.config_from_page(cfg, draft)
    assert any("Add-on setting" in e for e in errors)


def test_the_page_lists_providers_and_their_actions():
    providers = {p["id"]: p for p in page.providers_for_page()}
    fsrs = providers["fsrs_helper"]
    assert fsrs["unsupported"]  # no FSRS Helper in the headless suite
    assert {a["key"]: a["impact"] for a in fsrs["actions"]}["fsrs_helper/easy_dates"] == "read"


@pytest.mark.parametrize("change, message", [
    (lambda d: d["apps"].append({"name": "", "key": "x" * 20, "role": "default"}), "needs a name"),
    (lambda d: d["apps"].extend([{"name": "A", "key": "x" * 20, "role": "default"},
                                 {"name": "A", "key": "y" * 20, "role": "default"}]), "same name"),
    (lambda d: d["apps"].extend([{"name": "A", "key": "x" * 20, "role": "default"},
                                 {"name": "B", "key": "x" * 20, "role": "default"}]), "same key"),
    (lambda d: d["apps"].append({"name": "A", "key": "", "role": "default"}), "needs a key"),
    (lambda d: d["apps"].append({"name": "A", "key": "x" * 20, "role": "gone"}), "does not exist"),
    (lambda d: d["roles"].pop(), "cannot be deleted"),
    (lambda d: d["roles"].append({"id": "Bad Id", "name": "X", "grants": []}), "may only use"),
    (lambda d: d["roles"].append({"id": "x", "name": "X", "grants": ["root"]}), "unknown permission"),
    (lambda d: d.update(no_key_remote_role="default"), "Confirm that other devices"),
])
def test_invalid_drafts_are_refused(change, message):
    cfg = fresh()
    draft = draft_of(cfg)
    change(draft)
    new_cfg, _, errors = page.config_from_page(cfg, draft)
    assert new_cfg is cfg
    assert any(message in e for e in errors), errors


def test_opening_other_devices_needs_confirmation_once():
    cfg = fresh()
    draft = {**draft_of(cfg), "no_key_remote_role": "read_only", "confirm_remote": True}
    new_cfg, _, errors = page.config_from_page(cfg, draft)
    assert errors == [] and new_cfg["no_key_remote_role"] == "read_only"
    # Saving again without changing it needs no new confirmation.
    assert page.config_from_page(new_cfg, draft_of(new_cfg))[2] == []


def test_server_fields_still_flag_a_restart():
    cfg = fresh()
    draft = draft_of(cfg)
    draft["values"]["prefer_port"] = 8888
    assert page.config_from_page(cfg, draft)[1] is True


class FakeManager:
    def __init__(self, cfg, ankiconnect=None):
        self.cfg, self.ac = cfg, ankiconnect

    def getConfig(self, name):
        return self.ac if name == "2055492159" else self.cfg

    def allAddons(self):
        return ["2055492159"] if self.ac is not None else []

    def addon_meta(self, _name):
        return SimpleNamespace(enabled=False)


def bridge(cfg=None, ankiconnect=None):
    events = []
    mw = SimpleNamespace(addonManager=FakeManager(cfg or fresh(), ankiconnect))
    b = page.SettingsBridge(mw, restart=lambda enabled: events.append(("restart", enabled)),
                            close=lambda: events.append("close"),
                            copy=lambda text: events.append(("copy", text)))
    return b, events


def cmd(b, op, arg=None):
    return b.handle("tsunagi:" + json.dumps({"op": op, "arg": arg}))


def test_bridge_ignores_other_messages_and_reports_errors():
    b, _ = bridge()
    assert b.handle("domDone") is None
    assert "error" in cmd(b, "no_such_op")


def test_bridge_state_new_key_copy_and_close():
    b, events = bridge()
    state = cmd(b, "state")
    assert state["no_key_rows"][0]["role"] == "default"
    assert len(cmd(b, "new_key")) == 32
    cmd(b, "copy", "abc")
    cmd(b, "dirty", True)
    assert b.dirty is True  # X or Esc now asks first
    cmd(b, "close")  # Discard in that prompt
    assert events == [("copy", "abc"), "close"] and b.dirty is False


def test_bridge_reports_whether_the_server_runs(monkeypatch):
    b, _ = bridge()
    monkeypatch.setattr("tsunagi.app.server_url", lambda: "http://127.0.0.1:7777")
    assert cmd(b, "server_status") == {"running": True, "url": "http://127.0.0.1:7777"}
    monkeypatch.setattr("tsunagi.app.server_url", lambda: None)
    assert cmd(b, "server_status") == {"running": False, "url": None}


def test_bridge_save_applies_and_stays_open(monkeypatch):
    saved = []
    b, events = bridge()

    def save_settings(mw, cfg, disable_ankiconnect=False):
        saved.append((cfg, disable_ankiconnect))
        mw.addonManager.cfg = cfg  # what writing the config does
    monkeypatch.setattr("tsunagi.adapters.settings_dialog.save_settings", save_settings)
    draft = draft_of(fresh())
    draft["apps"] = [{"name": "Phone", "key": "p" * 32, "role": "read_only"}]
    res = cmd(b, "save", draft)
    assert res["ok"] and res["cfg"]["apps"][0]["name"] == "Phone"  # the page's new baseline
    assert saved[0][0]["apps"][0]["name"] == "Phone" and saved[0][1] is False
    assert events == []  # stays open; no server-level change, so no restart


def test_bridge_state_carries_what_the_page_edits_as_cfg():
    # Kiso's shell keeps state.cfg as the page's saved and draft config.
    b, _ = bridge()
    state = cmd(b, "state")
    assert state["cfg"] == page.page_draft(state) == draft_of(fresh())


def test_bridge_save_failure_is_an_error_kiso_can_show(monkeypatch):
    def fail(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr("tsunagi.adapters.settings_dialog.save_settings", fail)
    b, _ = bridge()
    assert cmd(b, "save", draft_of(fresh()))["errors"] == [
        {"message": "Could not save settings: disk full", "page": None, "field": None}]


def test_bridge_save_restarts_the_server_for_server_keys(monkeypatch):
    monkeypatch.setattr("tsunagi.adapters.settings_dialog.save_settings", lambda *a, **k: None)
    b, events = bridge()
    draft = draft_of(fresh())
    draft["values"]["log_level"] = "debug"
    assert cmd(b, "save", draft)["ok"]
    assert events == [("restart", True)]


def test_bridge_save_errors_keep_the_page_open(monkeypatch):
    monkeypatch.setattr("tsunagi.adapters.settings_dialog.save_settings",
                        lambda *a, **k: pytest.fail("must not save"))
    b, events = bridge()
    draft = {**draft_of(fresh()), "no_key_remote_role": "everything"}
    errors = cmd(b, "save", draft)["errors"]
    # Each error says where to fix it, so the page can take the user there.
    assert {"message": "Confirm that other devices may connect without a key.",
            "page": "nokey", "field": "confirmRemote"} in errors
    assert events == []


def test_bridge_previews_the_ankiconnect_takeover():
    ac = {"apiKey": "from-ac", "webBindPort": 8765, "webCorsOriginList": ["http://new"]}
    b, _ = bridge(ankiconnect=ac)
    assert cmd(b, "takeover_preview") == {"port_from": 7777, "port": 8765, "key": "new",
                                          "new_origins": ["http://new"], "enabled": False}
    assert cmd(bridge(ankiconnect={"webBindPort": 8765})[0], "takeover_preview")["key"] == "none"
    assert "error" in cmd(bridge()[0], "takeover_preview")


def test_bridge_takeover_hands_over_the_saved_config(monkeypatch):
    handovers = []
    monkeypatch.setattr("tsunagi.adapters.settings_dialog.save_settings",
                        lambda mw, cfg, **kw: handovers.append((cfg, kw)))
    ac = {"apiKey": "from-ac", "webBindPort": 8765, "webCorsOriginList": ["http://new"]}
    b, events = bridge(ankiconnect=ac)
    res = cmd(b, "takeover")
    [(cfg, kw)] = handovers
    assert kw == {"disable_ankiconnect": True} and cfg["port"] == cfg["prefer_port"] == 8765
    assert {"name": "AnkiConnect key", "key": "from-ac", "role": "default"} in cfg["apps"]
    assert res["ok"] and res["state"]["values"] and events == [("restart", True)]


def test_bridge_takeover_failure_is_reported(monkeypatch):
    def fail(*a, **k):
        raise ValueError("Port 8765 is still in use.")
    monkeypatch.setattr("tsunagi.adapters.settings_dialog.save_settings", fail)
    b, events = bridge(ankiconnect={"webBindPort": 8765})
    assert "Port 8765 is still in use." in cmd(b, "takeover")["error"]
    assert events == []


def test_state_offers_the_takeover_once():
    mw = SimpleNamespace(addonManager=FakeManager(fresh()))
    b = page.SettingsBridge(mw, restart=print, close=print, copy=print, offer_takeover=True)
    assert cmd(b, "state")["offer_takeover"] is True
    assert cmd(b, "state")["offer_takeover"] is False  # a Save reloads state; no second offer


def test_state_carries_defaults_and_restoring_keeps_import_history():
    cfg = {**fresh(), "apps": [{"name": "A", "key": "a" * 20, "role": "default"}],
           "ankiconnect_imported_at": "2026-09-01T12:00:00+00:00"}
    b, _ = bridge(cfg)
    state = cmd(b, "state")
    assert state["apps"] and state["defaults"]["apps"] == []
    restored, _, errors = page.config_from_page(cfg, draft_of(fresh()))
    assert errors == [] and restored["apps"] == []
    assert restored["ankiconnect_imported_at"] == cfg["ankiconnect_imported_at"]


def test_page_assets_are_inlined():
    html = page._page_html()
    assert "/*STYLE*/" not in html and "/*SCRIPT*/" not in html
    assert "pycmd(" in html and "--t-canvas" in html
    assert DEFAULTS["gates"]  # the page renders at least the server switches


def test_server_field_errors_point_at_their_field():
    cfg = fresh()
    draft = draft_of(cfg)
    draft["values"]["host"] = " "
    draft["values"]["op_timeout_seconds"] = 0
    _, _, errors = page.config_from_page(cfg, draft)
    assert [(e.page, e.field) for e in errors] == [("server", "host"), ("server", "op_timeout_seconds")]


def test_other_host_names_must_be_bare_host_names():
    cfg = fresh()
    draft = draft_of(cfg)
    draft["values"]["allowed_hosts"] = "pc.tailnet.ts.net\nhttps://pc.tailnet.ts.net:443"
    _, _, errors = page.config_from_page(cfg, draft)
    assert [(e.page, e.field) for e in errors] == [("server", "allowed_hosts")]
    draft["values"]["allowed_hosts"] = "pc.tailnet.ts.net\n\n pc.tailnet.ts.net "
    new_cfg, _, errors = page.config_from_page(cfg, draft)
    assert errors == [] and new_cfg["allowed_hosts"] == ["pc.tailnet.ts.net"]


def test_bridge_reads_and_clears_the_request_log():
    from tsunagi.adapters import request_log

    request_log.clear()
    request_log.add({"time": 1, "path": "/v1/decks", "app": "Yomitan", "status": 200})
    request_log.add({"time": 2, "path": "/v1/notes", "app": "Yomitan", "status": 403})
    b, _ = bridge()
    res = cmd(b, "requests", {"client": "app:Yomitan", "failed": True, "text": ""})
    assert [e["path"] for e in res["entries"]] == ["/v1/notes"]
    assert [(c["label"], c["requests"], c["failed"]) for c in res["clients"]] == [("Yomitan", 2, 1)]
    assert len(cmd(b, "requests")["entries"]) == 2  # no filters
    assert cmd(b, "clear_requests") is True and request_log.clients() == []


def test_saved_approvals_with_an_old_impact_show_disabled_and_do_not_block_save():
    cfg = {**fresh(), "addon_enabled": {"fsrs_helper/easy_days": "normal", "fsrs_helper/reschedule": "undoable"}}
    assert page.page_state(cfg, {})["addon_enabled"] == {"fsrs_helper/reschedule": "undoable"}
    new_cfg, _, errors = page.config_from_page(cfg, draft_of(cfg))
    assert errors == [] and new_cfg["addon_enabled"] == {"fsrs_helper/reschedule": "undoable"}
