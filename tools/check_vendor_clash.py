"""Another add-on loaded a different pydantic: Tsunagi says so instead of
failing with a traceback (backlog 8.3a), and logs it to Anki's per-add-on log
file (5.3). Runs the add-on's real startup code
(the root __init__.py) in a disposable profile."""
import importlib.util
import logging
import sys
import traceback
import types
from pathlib import Path
from unittest.mock import patch

from qt_smoke import run

REPO = Path(__file__).resolve().parents[1]


def check(app, screenshot):
    import aqt.utils

    mw = aqt.mw
    # The add-on package as Anki imports it (folder name aside).
    spec = importlib.util.spec_from_file_location(
        "tsunagi_addon", REPO / "__init__.py", submodule_search_locations=[str(REPO)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules["tsunagi_addon"] = addon
    spec.loader.exec_module(addon)

    other = Path(mw.addonManager.addonsFolder()) / "9999"
    (other / "pydantic").mkdir(parents=True)
    (other / "meta.json").write_text('{"name": "Some Other Add-on"}')
    fake = types.ModuleType("pydantic")
    fake.__file__ = str(other / "pydantic" / "__init__.py")
    fake.__version__ = "2.9.0"

    shown = []
    real = sys.modules.get("pydantic")
    sys.modules["pydantic"] = fake
    try:
        with patch.object(aqt.utils, "tooltip", lambda msg, **kw: shown.append(msg)):
            addon._on_profile_open()
    finally:
        if real is not None:
            sys.modules["pydantic"] = real
        else:
            sys.modules.pop("pydantic", None)
    # Refused before the server module (and FastAPI with it) was ever imported.
    assert "tsunagi_addon.tsunagi.app" not in sys.modules, "the server must not start"
    assert len(shown) == 1 and "Some Other Add-on" in shown[0] and "2.9.0" in shown[0], shown
    print("PASS: a clashing pydantic stops the server with a message naming the add-on", flush=True)

    # The same message is in Anki's per-add-on log file (backlog 5.3).
    for handler in logging.getLogger("addon.tsunagi_addon").handlers:
        handler.flush()
    log_file = Path(mw.addonManager.logs_folder("tsunagi_addon")) / "tsunagi_addon.log"
    assert "Tsunagi did not start" in log_file.read_text(encoding="utf-8"), log_file
    print(f"PASS: logged to Anki's add-on log ({log_file.name})", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    try:
        run(check, __doc__)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
