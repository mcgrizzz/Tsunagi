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
    state = page.page_state(cfg, {})
    draft = {"values": state["values"],
             "gates": {g["key"]: g["on"] for g in state["gates"]},
             "apps": state["apps"],
             "groups": [{k: g[k] for k in ("id", "name", "grants")} for g in state["groups"]]}
    for row in state["no_key_rows"]:
        draft[row["setting"]] = row["group"]
    return draft


def test_catalog_labels_every_permission():
    catalog = page.permission_catalog()
    listed = {a["area"] for a in catalog} | {n["name"] for a in catalog for n in a["names"]}
    assert {p for p in PERMISSIONS if p != PUBLIC} <= listed
    assert all(n["label"] for a in catalog for n in a["names"])


def test_untouched_draft_saves_the_same_config():
    cfg = fresh()
    new_cfg, restart, errors = page.config_from_page(cfg, draft_of(cfg))
    assert (new_cfg, restart, errors) == (cfg, False, [])


def test_apps_rows_and_groups_are_saved():
    cfg = fresh()
    draft = draft_of(cfg)
    draft["apps"] = [{"name": " Yomitan ", "key": "k" * 32, "group": "read_only"}]
    draft["no_key_local_group"] = "none"
    draft["groups"].append({"id": "custom_1", "name": "Tagger", "grants": ["read", "write:tags"]})
    new_cfg, restart, errors = page.config_from_page(cfg, draft)
    assert errors == [] and restart is False
    assert new_cfg["apps"] == [{"name": "Yomitan", "key": "k" * 32, "group": "read_only"}]
    assert new_cfg["no_key_local_group"] == "none"
    assert new_cfg["groups"] == {"custom_1": {"name": "Tagger", "grants": ["read", "write:tags"]}}


def test_only_edited_built_ins_are_stored_and_reset_removes_them():
    cfg = fresh()
    draft = draft_of(cfg)
    default = next(g for g in draft["groups"] if g["id"] == "default")
    default["grants"] = [g for g in default["grants"] if g != "manage"]
    edited, _, _ = page.config_from_page(cfg, draft)
    assert edited["groups"]["default"]["grants"] == sorted(
        {"read", "write", "gui", "sync", "events:changes"})
    state = page.page_state(edited, {})
    row = next(g for g in state["groups"] if g["id"] == "default")
    assert row["default"]["grants"] != row["grants"]  # the page offers Reset
    reset, _, _ = page.config_from_page(edited, draft_of(cfg))
    assert reset["groups"] == {}


@pytest.mark.parametrize("change, message", [
    (lambda d: d["apps"].append({"name": "", "key": "x" * 20, "group": "default"}), "needs a name"),
    (lambda d: d["apps"].extend([{"name": "A", "key": "x" * 20, "group": "default"},
                                 {"name": "A", "key": "y" * 20, "group": "default"}]), "same name"),
    (lambda d: d["apps"].extend([{"name": "A", "key": "x" * 20, "group": "default"},
                                 {"name": "B", "key": "x" * 20, "group": "default"}]), "same key"),
    (lambda d: d["apps"].append({"name": "A", "key": "", "group": "default"}), "needs a key"),
    (lambda d: d["apps"].append({"name": "A", "key": "x" * 20, "group": "gone"}), "does not exist"),
    (lambda d: d["groups"].pop(), "cannot be deleted"),
    (lambda d: d["groups"].append({"id": "Bad Id", "name": "X", "grants": []}), "may only use"),
    (lambda d: d["groups"].append({"id": "x", "name": "X", "grants": ["root"]}), "unknown permission"),
    (lambda d: d.update(no_key_remote_group="default"), "Confirm that other devices"),
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
    draft = {**draft_of(cfg), "no_key_remote_group": "read_only", "confirm_remote": True}
    new_cfg, _, errors = page.config_from_page(cfg, draft)
    assert errors == [] and new_cfg["no_key_remote_group"] == "read_only"
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
    b = page.SettingsBridge(mw, close=lambda saved: events.append(("close", saved)),
                            copy=lambda text: events.append(("copy", text)))
    return b, events


def cmd(b, op, arg=None):
    return b.handle("tsunagi:" + json.dumps({"op": op, "arg": arg}))


def test_bridge_ignores_other_messages_and_reports_errors():
    b, _ = bridge()
    assert b.handle("domDone") is None
    assert "error" in cmd(b, "no_such_op")


def test_bridge_state_new_key_copy_and_cancel():
    b, events = bridge()
    state = cmd(b, "state")
    assert state["no_key_rows"][0]["group"] == "default"
    assert len(cmd(b, "new_key")) == 32
    cmd(b, "copy", "abc")
    cmd(b, "cancel")
    assert events == [("copy", "abc"), ("close", False)]


def test_bridge_save_applies_and_closes(monkeypatch):
    saved = []
    monkeypatch.setattr("tsunagi.adapters.settings_dialog.save_settings",
                        lambda mw, cfg, disable_ankiconnect: saved.append((cfg, disable_ankiconnect)))
    b, events = bridge()
    draft = draft_of(fresh())
    draft["apps"] = [{"name": "Phone", "key": "p" * 32, "group": "read_only"}]
    assert cmd(b, "save", draft) == {"ok": True}
    assert saved[0][0]["apps"][0]["name"] == "Phone" and saved[0][1] is False
    assert events == [("close", True)] and b.restart is False


def test_bridge_save_errors_keep_the_page_open(monkeypatch):
    monkeypatch.setattr("tsunagi.adapters.settings_dialog.save_settings",
                        lambda *a, **k: pytest.fail("must not save"))
    b, events = bridge()
    draft = {**draft_of(fresh()), "no_key_remote_group": "everything"}
    assert "errors" in cmd(b, "save", draft)
    assert events == []


def test_bridge_stages_an_ankiconnect_import():
    ac = {"apiKey": "from-ac", "webBindPort": 8765, "webCorsOriginList": ["http://new"]}
    b, _ = bridge(ankiconnect=ac)
    res = cmd(b, "import_ankiconnect", draft_of(fresh()))
    assert res["values"]["port"] == 8765
    assert res["apps"] == [{"name": "AnkiConnect key", "key": "from-ac", "group": "default"}]
    assert res["pending"] == {"port": 8765, "key": "Copy from AnkiConnect", "origins": "1 new origin"}


def test_bridge_defaults_keep_import_history():
    cfg = {**fresh(), "apps": [{"name": "A", "key": "a" * 20, "group": "default"}],
           "ankiconnect_imported_at": "2026-09-01T12:00:00+00:00"}
    b, _ = bridge(cfg)
    state = cmd(b, "defaults")
    assert state["apps"] == [] and state["ankiconnect"]["imported"] is True


def test_page_assets_are_inlined():
    html = page._page_html()
    assert "/*STYLE*/" not in html and "/*SCRIPT*/" not in html
    assert "pycmd(" in html and "--t-canvas" in html
    assert DEFAULTS["gates"]  # the page renders at least the server switches
