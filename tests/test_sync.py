"""API sync through Anki's sync path without its dialogs (backlog 10.1, R17),
against stand-ins for AnkiWeb, the GUI hooks and Anki's task manager."""
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from tsunagi.adapters import ops
from tsunagi.adapters.jobs import jobs


def output(required=0):
    return SimpleNamespace(required=required, NO_CHANGES=0, NORMAL_SYNC=1, host_number=7,
                           new_endpoint="", server_message="")


class AnkiWeb:
    def __init__(self):
        self.calls = []
        self.status = 0          # SyncStatus.required before syncing
        self.result = output()   # what sync_collection returns
        self.error = None
        self.delay = 0.0
        self.auth = object()

    def sync_status(self, auth):
        self.calls.append("status")
        return SimpleNamespace(required=self.status, FULL_SYNC=2)

    def sync_collection(self, auth, media):
        self.calls.append(("sync", media))
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture()
def web(col, monkeypatch):
    import aqt
    mw = aqt.mw
    fake = AnkiWeb()
    monkeypatch.setattr(aqt, "gui_hooks", SimpleNamespace(
        sync_will_start=lambda: fake.calls.append("will_start"),
        sync_did_finish=lambda: fake.calls.append("did_finish")), raising=False)
    monkeypatch.setattr(mw, "pm", SimpleNamespace(
        name="User 1", sync_auth=lambda: fake.auth, media_syncing_enabled=lambda: True,
        set_host_number=lambda n: fake.calls.append(("host", n)),
        set_current_sync_url=lambda url: None,
        clear_sync_auth=lambda: fake.calls.append("logged_out")), raising=False)
    monkeypatch.setattr(mw, "reset", lambda: fake.calls.append("reset"), raising=False)
    # The screen Anki shows: redrawn at once, not left dimmed until focus.
    screen = SimpleNamespace(refresh_if_needed=lambda: fake.calls.append("redraw"))
    for name, value in (("state", "deckBrowser"), ("deckBrowser", screen), ("overview", None),
                        ("reviewer", None), ("fade_in_webview", lambda: fake.calls.append("undim"))):
        monkeypatch.setattr(mw, name, value, raising=False)
    monkeypatch.setattr(mw, "media_syncer", SimpleNamespace(
        start_monitoring=lambda: fake.calls.append("media")), raising=False)
    monkeypatch.setattr(col, "sync_status", fake.sync_status)
    monkeypatch.setattr(col, "sync_collection", fake.sync_collection)

    def run_in_background(task, on_done):
        # Anki runs `task` on a worker and `on_done` back on the main thread.
        def work():
            fut = Future()
            try:
                fut.set_result(task())
            except Exception as exc:
                fut.set_exception(exc)
            on_done(fut)
        threading.Thread(target=work).start()

    monkeypatch.setattr(mw.taskman, "run_in_background", run_in_background, raising=False)
    jobs.reset()
    yield fake
    jobs.reset()


def test_sync_runs_like_ankis_sync_button(client, web):
    resp = client.post("/v1/collection:sync")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == 0
    # Hooks around the sync (so FSRS Helper and others react), then Anki's
    # own follow-up: host number, refresh, media.
    assert web.calls == ["will_start", "status", ("sync", True), ("host", 7),
                         "did_finish", "reset", "redraw", "undim", "media"]


def test_full_sync_is_refused_before_anything_changes(client, web):
    web.status = 2
    resp = client.post("/v1/collection:sync")
    assert resp.status_code == 409 and "Click Sync in Anki" in resp.json()["detail"]
    assert ("sync", True) not in web.calls
    assert web.calls[-4:] == ["did_finish", "reset", "redraw", "undim"]  # hooks balanced; no media


def test_full_sync_reported_by_the_sync_itself_is_409(client, web):
    web.result = output(required=4)  # FULL_UPLOAD
    assert client.post("/v1/collection:sync").status_code == 409


def test_ankiweb_refusal_is_502_and_an_expired_login_is_cleared(client, web):
    web.error = RuntimeError("network down")
    resp = client.post("/v1/collection:sync")
    assert resp.status_code == 502 and resp.json()["detail"] == "Sync failed: network down"
    assert "logged_out" not in web.calls

    class AuthFailed(Exception):
        kind = SimpleNamespace(name="AUTH")
    web.error = AuthFailed("login expired")
    assert client.post("/v1/collection:sync").status_code == 502
    assert "logged_out" in web.calls


def test_no_sync_account_is_400_with_no_hooks(client, web):
    web.auth = None
    assert client.post("/v1/collection:sync").status_code == 400
    assert web.calls == []


def test_a_slow_sync_becomes_a_job(client, web, monkeypatch):
    monkeypatch.setattr(ops, "OP_TIMEOUT", 0.05)
    web.delay = 0.3
    resp = client.post("/v1/collection:sync")
    assert resp.status_code == 202
    job = resp.headers["location"]
    assert client.post(job + ":abort").status_code == 409  # not abortable
    deadline = time.monotonic() + 5
    while client.get(job).json()["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    polled = client.get(job).json()
    assert polled["status"] == "done" and polled["result"]["status"] == 0


def test_ankiconnect_sync_waits_for_the_end(client, web, monkeypatch):
    monkeypatch.setattr(ops, "OP_TIMEOUT", 0.05)
    web.delay = 0.2
    body = client.post("/", json={"action": "sync", "version": 6}).json()
    assert body == {"result": None, "error": None}
    assert "did_finish" in web.calls


def test_a_keyed_retry_syncs_once(client, web):
    # A keyed retry gets the same job, so AnkiWeb is asked once (6.74).
    from tsunagi.adapters import idempotency
    idempotency._journals.reset()
    first = client.post("/v1/collection:sync", headers={"Idempotency-Key": "s1"})
    again = client.post("/v1/collection:sync", headers={"Idempotency-Key": "s1"})
    assert first.status_code == again.status_code == 200
    assert again.headers["idempotent-replayed"] == "true"
    assert web.calls.count(("sync", True)) == 1
    idempotency._journals.reset()
