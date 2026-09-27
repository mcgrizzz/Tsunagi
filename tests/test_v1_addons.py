"""GET /v1/addons and add-on configs, against a fake AddonManager on a temp folder."""
import json
from types import SimpleNamespace

import pytest

from tsunagi.adapters.config import ADDON_PACKAGE

HELPER = "759844606"


def _addon(root, name, meta=None, defaults=None, schema=None):
    folder = root / name
    folder.mkdir()
    (folder / "__init__.py").write_text("")
    (folder / "meta.json").write_text(json.dumps(meta or {}))
    if defaults is not None:
        (folder / "config.json").write_text(json.dumps(defaults))
    if schema is not None:
        (folder / "config.schema.json").write_text(json.dumps(schema))


class FakeAddonManager:
    """The slice of aqt.addons.AddonManager the adapter uses, over the same folder
    layout. The headless suite stubs aqt; tools/check_addons_api.py runs these
    tests' scenarios against the real manager."""

    def __init__(self, root):
        self.root = root
        self._config_actions, self._updated_actions = {}, {}

    def _meta(self, name):
        return json.loads((self.root / name / "meta.json").read_text())

    def allAddons(self):
        return sorted(p.name for p in self.root.iterdir() if (p / "__init__.py").exists())

    def addon_meta(self, name):
        meta = self._meta(name)
        return SimpleNamespace(
            dir_name=name, enabled=not meta.get("disabled", False),
            installed_at=meta.get("mod", 0), human_version=meta.get("human_version"),
            homepage=meta.get("homepage"),
            human_name=lambda: meta.get("name") or name,
            ankiweb_id=lambda: int(name) if name.isdigit() else None,
            compatible=lambda: True)

    def all_addon_meta(self):
        return map(self.addon_meta, self.allAddons())

    def addonConfigDefaults(self, name):
        path = self.root / name / "config.json"
        return json.loads(path.read_text()) if path.exists() else None

    def getConfig(self, name):
        config = self.addonConfigDefaults(name)
        if config is None:
            return None
        config.update(self._meta(name).get("config", {}))
        return config

    def writeConfig(self, name, conf):
        meta = self._meta(name)
        meta["config"] = conf
        (self.root / name / "meta.json").write_text(json.dumps(meta))

    def _addon_schema(self, name):
        path = self.root / name / "config.schema.json"
        return json.loads(path.read_text()) if path.exists() else True

    def setConfigAction(self, name, fn):
        self._config_actions[name] = fn

    def configAction(self, name):
        return self._config_actions.get(name)

    def setConfigUpdatedAction(self, name, fn):
        self._updated_actions[name] = fn

    def configUpdatedAction(self, name):
        return self._updated_actions.get(name)


def populate(root):
    _addon(root, HELPER, meta={"name": "FSRS Helper", "config": {"easy_dates": ["2026-10-01"]}},
           defaults={"easy_dates": [], "auto_disperse": True},
           schema={"type": "object", "properties": {"easy_dates": {
               "type": "array", "items": {"type": "string"}}}})
    _addon(root, "plain", meta={"name": "No Config"})
    _addon(root, "off", meta={"name": "Disabled One", "disabled": True})
    _addon(root, ADDON_PACKAGE, meta={"name": "Tsunagi", "config": {"api_key": "secret"}},
           defaults={"api_key": "", "host": "127.0.0.1"})


@pytest.fixture
def manager(tmp_path, monkeypatch):
    import aqt

    populate(tmp_path)
    mgr = FakeAddonManager(tmp_path)
    monkeypatch.setattr(aqt.mw, "addonManager", mgr, raising=False)
    return mgr


@pytest.fixture
def gates(reset_settings):
    def enable(*names):
        reset_settings.update(gates={**reset_settings.get("gates"), **{n: True for n in names}})
    return enable


def test_list_reports_each_addon(client, manager):
    manager.setConfigAction(HELPER, lambda: None)
    items = {a["id"]: a for a in client.get("/v1/addons").json()["items"]}
    assert list(items) == sorted(items)
    helper = items[HELPER]
    assert (helper["name"], helper["ankiweb_id"], helper["enabled"]) == ("FSRS Helper", 759844606, True)
    assert helper["has_config"] and helper["has_config_ui"]
    assert items["plain"]["ankiweb_id"] is None and not items["plain"]["has_config"]
    assert items["off"]["enabled"] is False
    assert client.get(f"/v1/addons/{HELPER}").json() == helper
    assert client.get("/v1/addons/missing").status_code == 404


def test_config_read_needs_its_gate(client, manager, gates):
    response = client.get(f"/v1/addons/{HELPER}/config")
    assert response.status_code == 400 and "addons_read_config" in response.json()["detail"]
    gates("addons_read_config")
    config = client.get(f"/v1/addons/{HELPER}/config").json()["config"]
    assert config == {"easy_dates": ["2026-10-01"], "auto_disperse": True}  # defaults merged
    assert client.get("/v1/addons/plain/config").json()["config"] is None
    own = client.get(f"/v1/addons/{ADDON_PACKAGE}/config").json()["config"]
    assert own["api_key"] == "<redacted>" and own["host"] == "127.0.0.1"


def test_config_write_behaves_like_ankis_editor(client, manager, gates):
    body = {"config": {"easy_dates": ["2026-10-01", "2026-10-08"], "auto_disperse": True}}
    response = client.put(f"/v1/addons/{HELPER}/config", json=body)
    assert response.status_code == 400 and "addons_write_config" in response.json()["detail"]
    gates("addons_write_config")
    seen = []
    manager.setConfigUpdatedAction(HELPER, seen.append)

    rejected = client.put(f"/v1/addons/{HELPER}/config", json={"config": {"easy_dates": [5]}})
    assert rejected.status_code == 400 and "easy_dates/0" in rejected.json()["detail"]
    assert client.put(f"/v1/addons/{HELPER}/config", json=body).json()["changed"] is True
    assert seen == [body["config"]]
    assert manager.getConfig(HELPER) == body["config"]
    assert client.put(f"/v1/addons/{HELPER}/config", json=body).json()["changed"] is False
    assert seen == [body["config"]]  # unchanged: no second hook call


def test_config_write_refusals(client, manager, gates):
    gates("addons_write_config")
    own = client.put(f"/v1/addons/{ADDON_PACKAGE}/config", json={"config": {"api_key": ""}})
    assert own.status_code == 400 and "settings dialog" in own.json()["detail"]
    assert manager.getConfig(ADDON_PACKAGE)["api_key"] == "secret"
    assert client.put("/v1/addons/plain/config", json={"config": {}}).status_code == 400
    assert client.put("/v1/addons/missing/config", json={"config": {}}).status_code == 404


def test_capabilities_show_the_config_gates(client, manager, gates):
    operations = client.get("/v1/capabilities").json()["operations"]
    read = operations["GET /v1/addons/{addon_id}/config"]
    assert (read["status"], read["setting"]) == ("disabled", "gates.addons_read_config")
    assert operations["PUT /v1/addons/{addon_id}/config"]["status"] == "disabled"
    assert operations["GET /v1/addons"]["status"] == "available"
    gates("addons_read_config")
    assert client.get("/v1/capabilities").json()["operations"][
        "GET /v1/addons/{addon_id}/config"]["status"] == "available"
