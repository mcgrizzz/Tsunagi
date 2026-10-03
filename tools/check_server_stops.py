"""Stopping the server while a request waits on Anki's main thread (backlog 6.80).
The settings page's restart and the add-on switch's Stop now don't block Anki:
the request gets its answer, then the server restarts or stays off. Closing the
profile has to stop at once, before the collection closes: the waiting request
gets a 503 saying so, not a 500 after uvicorn's 3 s shutdown limit."""

# isort: off
# kiso_dev.harness sets Qt up for offscreen use before aqt loads, so it comes first.
from kiso_dev.harness import addon, run, until

import socket
import sys
import threading
import time
from unittest.mock import patch

import aqt
import aqt.utils
import httpx
# isort: on


def get(url, box):
    try:
        box.append(httpx.get(url, timeout=60).status_code)
    except Exception as exc:
        box.append(repr(exc))


def check(app, shots, base):
    root = addon()

    def app_module():
        return sys.modules[root.__name__ + ".tsunagi.app"]

    def bound():
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", 7777)) == 0

    def waiting_request():
        """A read sent while Anki's main thread is busy, so it waits on it."""
        until(app, bound, 30, "the server never took its port")
        box = []
        thread = threading.Thread(target=get, args=(app_module().server_url() + "/v1/decks", box))
        thread.start()
        time.sleep(0.5)
        return thread, box

    def timed(fn):
        began = time.monotonic()
        fn()
        return time.monotonic() - began

    shown = []
    with patch.object(aqt.utils, "tooltip", lambda msg, **kw: shown.append(msg)):
        settings_dialog = sys.modules.get(root.__name__ + ".tsunagi.adapters.settings_dialog")
        if settings_dialog is None:
            import importlib
            settings_dialog = importlib.import_module(root.__name__ + ".tsunagi.adapters.settings_dialog")
        thread, box = waiting_request()
        blocked = timed(lambda: settings_dialog._restart_server(aqt.mw, enabled=True))
        assert blocked < 1, f"the settings restart held Anki's main thread for {blocked:.1f} s"
        until(app, lambda: not thread.is_alive(), 30)
        assert box == [200], f"the waiting request got {box}"
        until(app, lambda: any(m.startswith("Tsunagi server restarted") for m in shown), 30, f"no restart: {shown}")
        assert app_module().server_url()
        print("PASS: the settings page's restart lets the request in progress finish, without blocking Anki",
              flush=True)

        thread, box = waiting_request()
        blocked = timed(root._stop_now)
        assert blocked < 1, f"Stop now held Anki's main thread for {blocked:.1f} s"
        until(app, lambda: not thread.is_alive(), 30)
        assert box == [200], f"the waiting request got {box}"
        until(app, lambda: "Tsunagi's server stopped." in shown, 30, f"no stop: {shown}")
        assert app_module().server_url() is None
        until(app, lambda: not bound(), 30, "the port stayed taken")
        print("PASS: Stop now lets the request in progress finish, without blocking Anki", flush=True)

    app_module().start_server(aqt.mw)
    thread, box = waiting_request()
    took = timed(lambda: app_module().stop_server("profile_closed"))   # what closing the profile does
    until(app, lambda: not thread.is_alive(), 30)
    assert box == [503], f"the waiting request got {box}"
    assert took < 2, f"closing the profile waited {took:.1f} s for the server"
    print("PASS: closing the profile answers the waiting request 503 and stops at once", flush=True)


if __name__ == "__main__":
    run(check, __doc__)
