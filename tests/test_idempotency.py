"""Idempotency-Key on creating notes and media (backlog 6.2b)."""
import base64

import pytest
from access import key_required

from tsunagi.adapters import idempotency, ops
from tsunagi.http.v1 import notes as notes_route


def note(front="hello"):
    return {"model_name": "Basic", "deck_name": "Default", "fields": {"Front": front, "Back": "x"}}


@pytest.fixture(autouse=True)
def clean_store():
    idempotency.store.reset()
    yield
    idempotency.store.reset()


def post_note(client, body, key, **headers):
    return client.post("/v1/notes", json=body, headers={"Idempotency-Key": key, **headers})


def test_a_repeat_returns_the_first_response_and_writes_once(client, col):
    first = post_note(client, note(), "k1")
    again = post_note(client, note(), "k1")
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json() and len(first.json()["created"]) == 1
    assert "idempotent-replayed" not in first.headers
    assert again.headers["idempotent-replayed"] == "true"
    assert col.note_count() == 1


def test_without_a_key_nothing_changes(client, col):
    client.post("/v1/notes", json=note("a"))
    client.post("/v1/notes", json=note("b"))
    assert col.note_count() == 2


def test_a_write_that_completes_after_a_503_is_returned_to_the_retry(client, col, monkeypatch):
    # The first attempt outlasts op_timeout_seconds: 503, but the write is
    # still queued and completes later. The retry must not write again.
    queued = []
    monkeypatch.setattr(notes_route, "collection_op_run_async",
                        lambda fn, *a, on_success, on_failure, **kw: queued.append((fn, a, kw, on_success)))
    monkeypatch.setattr(ops, "op_timeout", lambda: 0.05)
    first = post_note(client, note(), "late")
    assert first.status_code == 503 and "retry with the same Idempotency-Key" in first.json()["detail"]
    assert post_note(client, note(), "late").status_code == 503  # still running: waits, starts nothing
    assert len(queued) == 1

    fn, args, kwargs, on_success = queued[0]
    on_success(fn(col, *args, **kwargs).value)   # Anki finally runs it
    retry = post_note(client, note(), "late")
    assert retry.status_code == 200 and retry.headers["idempotent-replayed"] == "true"
    assert len(retry.json()["created"]) == 1 and col.note_count() == 1


def test_a_key_reused_for_a_different_request_is_refused(client, col):
    post_note(client, note("one"), "k2")
    resp = post_note(client, note("two"), "k2")
    assert resp.status_code == 400 and "different request" in resp.json()["detail"]
    assert col.note_count() == 1


def test_keys_belong_to_each_app(client, col, reset_settings):
    reset_settings.update(**{**key_required("a" * 32, name="Yomitan"),
                             "apps": [{"name": "Yomitan", "key": "a" * 32, "role": "default"},
                                      {"name": "Phone", "key": "b" * 32, "role": "default"}]})
    post_note(client, note("from yomitan"), "same", **{"X-Api-Key": "a" * 32})
    other = post_note(client, note("from phone"), "same", **{"X-Api-Key": "b" * 32})
    assert "idempotent-replayed" not in other.headers  # not Yomitan's key, not a refusal
    assert col.note_count() == 2


def test_a_failed_first_attempt_is_forgotten(client, col, monkeypatch):
    calls = []

    def flaky(fn, *a, on_success, on_failure, **kw):
        calls.append(1)
        if len(calls) == 1:
            on_failure(RuntimeError("disk full"))
        else:
            on_success(fn(col, *a, **kw).value)
    monkeypatch.setattr(notes_route, "collection_op_run_async", flaky)
    assert post_note(client, note(), "k3").status_code == 500
    assert post_note(client, note(), "k3").status_code == 200
    assert len(calls) == 2 and col.note_count() == 1


def test_media_repeats_store_once(client, col):
    body = {"filename": "hello.txt", "data": base64.b64encode(b"hi").decode()}
    first = client.post("/v1/media", json=body, headers={"Idempotency-Key": "m1"})
    again = client.post("/v1/media", json=body, headers={"Idempotency-Key": "m1"})
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json() and again.headers["idempotent-replayed"] == "true"
    assert col.media.have("hello.txt") and not col.media.have("hello-1.txt")


def test_keyed_media_keeps_the_callers_permissions(client, col, reset_settings, tmp_path):
    # The upload runs on its own thread; a local file still needs local_files.
    source = tmp_path / "pic.txt"
    source.write_text("x")
    body = {"filename": "pic.txt", "path": str(source)}
    denied = client.post("/v1/media", json=body, headers={"Idempotency-Key": "m2"}).json()
    assert denied["created"] == [] and denied["failed"]
    reset_settings.update(no_key_local_role="everything")
    allowed = client.post("/v1/media", json=body, headers={"Idempotency-Key": "m3"}).json()
    assert [c["filename"] for c in allowed["created"]] == ["pic.txt"]


def test_finished_keys_expire(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(idempotency.time, "monotonic", lambda: now[0])
    entry, new = idempotency.store.begin(("app", "r", "k"), "f")
    idempotency.store.complete(entry, {"ok": True})
    assert idempotency.store.begin(("app", "r", "k"), "f") == (entry, False)
    now[0] += idempotency.TTL + 1
    assert idempotency.store.begin(("app", "r", "k"), "f")[1] is True

