"""
Idempotency-Key beyond collection writes (backlog 6.74): a keyed retry of a
job gets the same job, and an action on Anki's main thread runs once, even
when it finished after the first attempt's 503.
"""
import threading

import pytest
from fakes.anki_stubs import mw

from tsunagi.adapters import idempotency, ops
from tsunagi.adapters.jobs import jobs


@pytest.fixture(autouse=True)
def clean():
    idempotency._journals.reset()
    jobs.reset()
    yield
    idempotency._journals.reset()
    jobs.reset()


def keyed(key):
    return {"Idempotency-Key": key}


def test_a_retried_job_is_the_same_job(client):
    first = client.post("/v1/fsrs:compute-params", json={}, headers=keyed("k1"))
    again = client.post("/v1/fsrs:compute-params", json={}, headers=keyed("k1"))
    assert first.status_code == again.status_code == 202
    assert again.json()["job_id"] == first.json()["job_id"]
    assert again.headers["idempotent-replayed"] == "true"
    assert len(jobs._jobs) == 1


def test_without_a_key_a_job_runs_again(client):
    first = client.post("/v1/fsrs:compute-params", json={})
    again = client.post("/v1/fsrs:compute-params", json={})
    assert again.json()["job_id"] != first.json()["job_id"]


def test_a_retried_import_imports_once(client, monkeypatch):
    from tsunagi.http.v1 import collection

    calls = []

    def submit(path, *, on_started, on_success, on_failure, **options):
        calls.append(path)
        on_started()
        on_success({"imported": 3, "updated": 0})

    monkeypatch.setattr(collection, "submit_import_package", submit)
    first = client.post("/v1/collection:import", json={"path": "deck.apkg"}, headers=keyed("k1"))
    again = client.post("/v1/collection:import", json={"path": "deck.apkg"}, headers=keyed("k1"))
    assert first.status_code == again.status_code == 200
    assert again.json()["imported"] == first.json()["imported"] == 3
    assert again.headers["idempotent-replayed"] == "true"
    assert calls == ["deck.apkg"]


def test_a_failed_import_keeps_its_status_and_runs_again(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for _ in range(2):
        resp = client.post("/v1/collection:import", json={"path": ""}, headers=keyed("k1"))
        assert resp.status_code == 400 and "idempotent-replayed" not in resp.headers


def test_a_main_thread_action_that_ends_after_a_503_runs_once(client, monkeypatch):
    # gui:deck-browser: the first attempt outlasts op_timeout_seconds and
    # answers 503, but Anki runs the queued call later. The retry gets that
    # result instead of running it a second time.
    moves, queued = [], []
    monkeypatch.setattr(mw, "moveToState", moves.append, raising=False)
    monkeypatch.setattr(mw.taskman, "run_on_main", queued.append)
    monkeypatch.setattr(ops, "op_timeout", lambda: 0.05)
    first = client.post("/v1/gui:deck-browser", headers=keyed("late"))
    assert first.status_code == 503
    for call in queued:
        call()
    again = client.post("/v1/gui:deck-browser", headers=keyed("late"))
    assert again.status_code == 200 and again.headers["idempotent-replayed"] == "true"
    assert moves == ["deckBrowser"]


def test_export_with_a_key_exports_once(client, monkeypatch, tmp_path):
    from tsunagi.adapters.anki import collection as adapter

    calls = []
    monkeypatch.setattr(adapter, "_export_package", lambda col, *a, **k: calls.append(a))
    path = str(tmp_path / "out.apkg")
    for _ in range(2):
        resp = client.post("/v1/collection:export", json={"deck_name": "Default", "path": path},
                           headers=keyed("k1"))
        assert resp.status_code == 200
    assert len(calls) == 1 and resp.headers["idempotent-replayed"] == "true"


def test_a_step_inside_a_step_is_part_of_it(col):
    # Starting a job makes a main-thread call of its own. On a retry the job's
    # start is replayed without that call, so the call must not take a slot:
    # the request's next step would get the wrong recorded result.
    def run(journal, calls):
        token = ops.write_journal.set(journal)
        try:
            outer = ops.recorded(lambda ok, fail: ok(("outer", ops.call_on_main(calls.append, "inner"))))
            after = ops.call_on_main(lambda: calls.append("after") or "after")
        finally:
            ops.write_journal.reset(token)
        idempotency.close_journal(journal)
        return outer, after

    def on_worker(journal, calls):  # as a request runs; on the main thread nothing is recorded
        out = []
        worker = threading.Thread(target=lambda: out.append(run(journal, calls)))
        worker.start()
        worker.join()
        return out[0]

    calls = []
    scope = ("app", "POST", "/v1/x", "k")
    first = on_worker(idempotency.open_journal(scope, "f"), calls)
    again = on_worker(idempotency.open_journal(scope, "f"), calls)
    assert first == again == (("outer", None), "after")
    assert calls == ["inner", "after"]
