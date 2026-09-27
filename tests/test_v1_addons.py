"""GET /v1/addons, against a fake AddonManager on a temp folder."""
import json
from types import SimpleNamespace

import pytest

from tsunagi.adapters.config import ADDON_PACKAGE

HELPER = "759844606"


def _addon(root, name, meta=None, defaults=None):
    folder = root / name
    folder.mkdir()
    (folder / "__init__.py").write_text("")
    (folder / "meta.json").write_text(json.dumps(meta or {}))
    if defaults is not None:
        (folder / "config.json").write_text(json.dumps(defaults))


class FakeAddonManager:
    """The slice of aqt.addons.AddonManager the adapter uses, over the same folder
    layout. The headless suite stubs aqt; tools/check_addons_api.py runs these
    tests' scenarios against the real manager."""

    def __init__(self, root):
        self.root = root
        self._config_actions = {}

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

    def setConfigAction(self, name, fn):
        self._config_actions[name] = fn

    def configAction(self, name):
        return self._config_actions.get(name)



def populate(root):
    _addon(root, HELPER, meta={"name": "FSRS Helper"}, defaults={"easy_dates": []})
    _addon(root, "plain", meta={"name": "No Config"})
    _addon(root, "off", meta={"name": "Disabled One", "disabled": True})
    _addon(root, ADDON_PACKAGE, meta={"name": "Tsunagi"}, defaults={"api_key": ""})


@pytest.fixture
def manager(tmp_path, monkeypatch):
    import aqt

    populate(tmp_path)
    mgr = FakeAddonManager(tmp_path)
    monkeypatch.setattr(aqt.mw, "addonManager", mgr, raising=False)
    return mgr


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


def test_config_routes_are_not_offered(client, manager):
    # Add-ons expose data and actions through providers, not raw settings.
    assert client.get(f"/v1/addons/{HELPER}/config").status_code == 404
    assert client.put(f"/v1/addons/{HELPER}/config", json={"config": {}}).status_code in (404, 405)
