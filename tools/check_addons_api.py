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
    from tsunagi.shared.errors import ResourceNotFoundError

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


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    try:
        run(check, __doc__)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
