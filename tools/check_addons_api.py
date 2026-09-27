"""Check the add-on adapter against Anki's real AddonManager in a disposable profile.

The headless suite (tests/test_v1_addons.py) uses a fake manager because it
stubs aqt; this runs the same scenarios against the real one.
"""
import sys
import traceback
from pathlib import Path

from qt_smoke import aqt, run


def check(app, screenshot):
    from test_v1_addons import HELPER, populate

    from tsunagi.adapters.anki import addons
    from tsunagi.adapters.config import ADDON_PACKAGE
    from tsunagi.shared.errors import ResourceNotFoundError, ValidationError

    mgr = aqt.mw.addonManager
    root = Path(mgr.addonsFolder())
    populate(root)
    mgr.setConfigAction(HELPER, lambda: None)

    items = {a["id"]: a for a in addons.list_addons()}
    helper = items[HELPER]
    assert (helper["name"], helper["ankiweb_id"], helper["enabled"]) == ("FSRS Helper", 759844606, True)
    assert helper["has_config"] and helper["has_config_ui"] and helper["compatible"]
    assert items["plain"]["ankiweb_id"] is None and not items["plain"]["has_config"]
    assert items["off"]["enabled"] is False
    assert addons.get_addon(HELPER) == helper
    try:
        addons.get_addon("missing")
        raise AssertionError("missing add-on was found")
    except ResourceNotFoundError:
        pass
    print("PASS: listing matches the real AddonManager's metadata", flush=True)

    assert addons.read_addon_config(HELPER) == {"easy_dates": ["2026-10-01"], "auto_disperse": True}
    assert addons.read_addon_config("plain") is None
    assert addons.read_addon_config(ADDON_PACKAGE)["api_key"] == "<redacted>"
    print("PASS: config reads merge defaults and redact Tsunagi's key", flush=True)

    seen = []
    mgr.setConfigUpdatedAction(HELPER, seen.append)
    new = {"easy_dates": ["2026-10-01", "2026-10-08"], "auto_disperse": True}
    try:
        addons.write_addon_config(HELPER, {"easy_dates": [5]})
        raise AssertionError("schema violation was accepted")
    except ValidationError as e:
        assert "easy_dates/0" in str(e)
    assert addons.write_addon_config(HELPER, new) is True
    assert seen == [new] and mgr.getConfig(HELPER) == new
    assert addons.write_addon_config(HELPER, new) is False and seen == [new]
    for addon_id, conf in ((ADDON_PACKAGE, {"api_key": ""}), ("plain", {})):
        try:
            addons.write_addon_config(addon_id, conf)
            raise AssertionError(f"write to {addon_id} was accepted")
        except ValidationError:
            pass
    assert mgr.getConfig(ADDON_PACKAGE)["api_key"] == "secret"
    print("PASS: config writes validate, call the hook once, and refuse Tsunagi's own", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    try:
        run(check, __doc__)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
