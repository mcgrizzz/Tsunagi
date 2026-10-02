"""Another add-on loaded a different pydantic: Tsunagi says so instead of
failing with a traceback (backlog 8.3a), and logs it to Anki's per-add-on log
file (5.3). Runs in real Anki with the add-on installed through its root
__init__.py; the clash appears before a reload, whose start goes the same way
as the first one."""

# isort: off
# kiso_dev.harness sets Qt up for offscreen use before aqt loads, so it comes first.
from kiso_dev.harness import addon, run, until

import logging
import sys
import types
from pathlib import Path
from unittest.mock import patch

import aqt
import aqt.utils
# isort: on


def check(app, shots, base):
    mw = aqt.mw
    root = addon()
    assert sys.modules[root.__name__ + ".tsunagi.app"].server_url(), "the server didn't start"

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
            root.reload_addon()
            until(app, lambda: any(m.startswith("Tsunagi: reloaded") for m in shown), 30,
                  f"the reload never finished: {shown}")
    finally:
        sys.modules["pydantic"] = real
    # Refused before the server module (and FastAPI with it) was imported again.
    assert root.__name__ + ".tsunagi.app" not in sys.modules, "the server must not start"
    refusals = [m for m in shown if "Some Other Add-on" in m]
    assert len(refusals) == 1 and "2.9.0" in refusals[0], shown
    print("PASS: a clashing pydantic stops the server with a message naming the add-on", flush=True)

    # The same message is in Anki's per-add-on log file (backlog 5.3).
    for handler in logging.getLogger("addon." + root.__name__).handlers:
        handler.flush()
    log_file = Path(mw.addonManager.logs_folder(root.__name__)) / f"{root.__name__}.log"
    assert "Tsunagi did not start" in log_file.read_text(encoding="utf-8"), log_file
    print(f"PASS: logged to Anki's add-on log ({log_file.name})", flush=True)


if __name__ == "__main__":
    run(check, __doc__)
