"""Resending a write safely (6.143): the server session on every /v1 response,
If-Session refused with a 412 once Anki restarted or switched profile, the
key's retention in the API description, and keys kept for all of it."""
import logging

import pytest

from tsunagi.adapters import idempotency
from tsunagi.adapters.events import broker


def note(front="hello"):
    return {"note_type_name": "Basic", "deck_name": "Default", "fields": {"Front": front, "Back": "x"}}


@pytest.fixture(autouse=True)
def session(col):
    idempotency.store.reset()
    yield broker.start_session(col, profile="User 1")
    broker.reset()
    idempotency.store.reset()


def test_every_v1_response_carries_the_session(client, session):
    for response in (client.get("/v1/health"), client.get("/v1/notes?limit=1"),
                     client.get("/v1/notes/1"), client.post("/v1/notes", json=[note()])):
        assert response.headers["tsunagi-session"] == session, response.request.url
    assert "tsunagi-session" not in client.get("/docs").headers


def test_a_resend_in_the_same_session_answers_the_first_attempt(client, col, session):
    headers = {"Idempotency-Key": "k1"}
    first = client.post("/v1/notes", json=[note()], headers=headers)
    again = client.post("/v1/notes", json=[note()], headers={**headers, "If-Session": session})
    assert again.status_code == 200 and again.json() == first.json()
    assert again.headers["idempotent-replayed"] == "true" and col.note_count() == 1


def test_a_resend_after_a_restart_or_switch_is_refused(client, col, session):
    client.post("/v1/notes", json=[note()], headers={"Idempotency-Key": "k1"})
    restarted = broker.start_session(col, profile="User 1")
    for path, body in (("/v1/notes", [note()]), ("/v1/cards:suspend", {"card_ids": []})):
        response = client.post(path, json=body, headers={"Idempotency-Key": "k1", "If-Session": session})
        assert response.status_code == 412, path
        assert "Check before writing again" in response.json()["detail"]
        assert response.headers["tsunagi-session"] == restarted
    assert col.note_count() == 1


def test_ready_names_the_profile(session):
    ready = broker.ready(broker.subscribe())
    assert ready["type"] == "ready" and ready["session_id"] == session and ready["profile"] == "User 1"


def test_the_description_gives_the_keys_retention(client):
    parameter = client.get("/openapi.json").json()["components"]["parameters"]["IdempotencyKey"]
    assert parameter["x-retention-seconds"] == idempotency.TTL == 600


def test_keys_are_kept_their_whole_retention(monkeypatch, caplog):
    now = [1000.0]
    monkeypatch.setattr(idempotency.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(idempotency, "MAX_ENTRIES", 3)
    store = idempotency.store
    running, _ = store.begin(("app", "r", "running"), "f")  # not finished: never forgotten
    for i in range(3):
        entry, _ = store.begin(("app", "r", f"k{i}"), "f")
        store.complete(entry, {})
    with caplog.at_level(logging.WARNING, logger=idempotency.__name__):
        store.begin(("app", "r", "k3"), "f")
    assert "Forgot 1 Idempotency-Keys before their 600 s" in caplog.text
    assert store.begin(("app", "r", "k0"), "f")[1] is True  # the oldest finished went first
    assert store.begin(("app", "r", "running"), "f") == (running, False)
    now[0] += idempotency.TTL + 1
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=idempotency.__name__):
        store.begin(("app", "r", "new"), "f")
    assert not caplog.text  # past their retention: forgotten quietly
    assert store.begin(("app", "r", "running"), "f") == (running, False)
