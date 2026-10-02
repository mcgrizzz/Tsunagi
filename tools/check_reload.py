"""Reloading Tsunagi (what `kiso sync --watch` triggers) while a request waits
on Anki's main thread: the reload doesn't block Anki, the request gets its
answer, and the new server is up afterwards. Before, the reload blocked the
main thread until uvicorn cancelled the request (a 500), and on Linux and
macOS the new server then found its port "busy" and didn't start."""

# isort: off
# kiso_dev.harness sets Qt up for offscreen use before aqt loads, so it comes first.
from kiso_dev.harness import addon, run, until

import socket
import sys
import threading
import time
from unittest.mock import patch

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
    server = sys.modules[root.__name__ + ".tsunagi.app"]
    url = server.server_url()
    assert url, "the server didn't start at profile open"
    port = int(url.rsplit(":", 1)[1])

    def bound():
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", port)) == 0
    until(app, bound, 30, "the server never took its port")
    box = []
    t = threading.Thread(target=get, args=(url + "/v1/decks", box))
    t.start()
    until(app, lambda: not t.is_alive(), 30)
    assert box == [200], box

    # A read waits on Anki's main thread; send one while the main thread is busy.
    box, shown = [], []
    t = threading.Thread(target=get, args=(url + "/v1/decks", box))
    t.start()
    time.sleep(0.5)
    with patch.object(aqt.utils, "tooltip", lambda msg, **kw: shown.append(msg)):
        began = time.monotonic()
        message = root.reload_addon()
        blocked = time.monotonic() - began
        assert message.startswith("reloading once"), message
        assert blocked < 1, f"the reload held Anki's main thread for {blocked:.1f} s"
        until(app, lambda: not t.is_alive(), 30, "the waiting request never finished")
        assert box == [200], f"the waiting request got {box}"
        until(app, lambda: shown, 30, "the reload never finished")
    assert shown[0].startswith("Tsunagi: reloaded"), shown
    print("PASS: a reload lets the request in progress finish, without blocking Anki", flush=True)

    server = sys.modules[root.__name__ + ".tsunagi.app"]   # the reloaded module
    assert server.server_url() == url, server.server_url()
    box = []
    t = threading.Thread(target=get, args=(url + "/v1/decks", box))
    t.start()
    until(app, lambda: not t.is_alive(), 30)
    assert box == [200], box
    print("PASS: the reloaded server answers on the same port", flush=True)


if __name__ == "__main__":
    run(check, __doc__)
