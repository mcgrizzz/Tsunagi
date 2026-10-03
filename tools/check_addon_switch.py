"""Turning Tsunagi off in Tools > Add-ons offers to stop its server now
(backlog 6.42); turning it back on in the same session starts the server
again, and both say so."""

# isort: off
# kiso_dev.harness sets Qt up for offscreen use before aqt loads, so it comes first.
from kiso_dev.harness import addon, run, until

import importlib
import sys
from unittest.mock import patch

import aqt
import aqt.utils
# isort: on


def check(app, shots, base):
    name = addon().__name__
    manager = aqt.mw.addonManager

    def url():
        return sys.modules[name + ".tsunagi.app"].server_url()
    assert url(), "the server didn't start"
    toggle = importlib.import_module(name + ".tsunagi.adapters.addon_toggle")
    shown = []
    with patch.object(toggle, "ask_to_stop", lambda parent: True), \
            patch.object(aqt.utils, "tooltip", lambda msg, **kw: shown.append(msg)):
        manager.toggleEnabled(name, False)
        assert url() is None and not manager.addon_meta(name).enabled
        # Said once the server has stopped: the stop lets requests in progress finish (6.80).
        until(app, lambda: shown, 10, "Stop now never said it stopped")
        assert shown == ["Tsunagi's server stopped."], shown
        print("PASS: turning Tsunagi off stops its server when asked", flush=True)
        manager.toggleEnabled(name, True)
        assert url() and manager.addon_meta(name).enabled
        assert shown[1:] == ["Tsunagi's server is running again."], shown
    print("PASS: turning it back on starts the server again and says so", flush=True)


if __name__ == "__main__":
    run(check, __doc__)
