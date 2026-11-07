"""Add-on events: a provider declares events and sends them on the event
stream as addons.<provider>.<event> (docs/addon_providers.md)."""
import logging
import threading

import pytest
from test_v1_events import parse_frames

from tsunagi.adapters import addon_actions as actions
from tsunagi.adapters.addon_actions import Registry
from tsunagi.adapters.events import broker

pytestmark = pytest.mark.usefixtures("review_events")

SET_DONE = "addons.hitoiki.set_done"
NO_ADDONS = {"roles": {"changes": {"name": "Changes", "grants": ["read:collection", "events:changes"]}},
             "no_key_local_role": "changes"}


@pytest.fixture(autouse=True)
def clean_broker():
    broker.reset()
    yield
    broker.reset()


@pytest.fixture()
def hitoiki(monkeypatch):
    monkeypatch.setattr(actions, "PROVIDERS", {})
    return Registry().provide("hitoiki", "Hitoiki", actions=[], events=[
        {"name": "set_done", "title": "Set done", "description": "A set of cards was finished."},
        {"name": "break_over"},
    ])


def stream(client, emitter, query, *sends):
    threading.Timer(0.2, lambda: [emitter.emit(*send) for send in sends]).start()
    response = client.get(f"/v1/events?timeout=0.6&{query}")
    assert response.status_code == 200, response.text
    return parse_frames(response.text)


def test_an_emitted_event_arrives_with_its_payload(client, hitoiki):
    payload = {"deck": "Japanese", "count": 20, "goal": 20, "ms": 512000}
    frames = stream(client, hitoiki, f"types={SET_DONE}", ("set_done", payload))
    assert [name for name, _ in frames] == ["ready", SET_DONE, "close"]
    event = frames[1][1]
    assert event["payload"] == payload
    assert set(event) == {"type", "payload", "seq", "session_id", "ts"}
    assert frames[0][1]["resources"] == ["addons"]


@pytest.mark.parametrize("query, arrives", [
    ("", True),
    ("resources=addons", True),
    ("resources=notes,addons", True),
    ("types=addons.hitoiki.break_over", False),
    ("resources=notes", False),
    ("types=change", False),
    ("types=sync", False),
])
def test_which_streams_get_add_on_events(client, hitoiki, query, arrives):
    frames = stream(client, hitoiki, query, ("set_done", {"count": 1}))
    assert (SET_DONE in [name for name, _ in frames]) is arrives


def test_resources_addons_lists_addons_in_ready(client, hitoiki):
    frames = stream(client, hitoiki, "resources=notes,addons")
    assert frames[0][1]["resources"] == ["addons", "notes"]


def test_an_event_no_add_on_declares_is_refused(client, hitoiki):
    for query in ("types=addons.hitoiki.nope", "types=addons.other.set_done", "resources=addon"):
        assert client.get(f"/v1/events?{query}").status_code == 422


def test_add_on_events_need_read_addons(client, hitoiki, reset_settings):
    reset_settings.update(**NO_ADDONS)
    frames = stream(client, hitoiki, "", ("set_done", {}))
    assert SET_DONE not in [name for name, _ in frames]
    assert "addons" not in frames[0][1]["resources"]
    report = client.get("/v1/capabilities").json()
    assert report["operations"]["GET /v1/events"]["options"]["addons"]["status"] == "disabled"


def test_emit_never_raises_and_logs_what_it_drops(client, hitoiki, caplog, monkeypatch):
    token = broker.subscribe()
    with caplog.at_level(logging.WARNING, logger=actions.__name__):
        hitoiki.emit("undeclared", {})
        hitoiki.emit("set_done", {"when": object()})
        hitoiki.emit("set_done", {"ms": float("nan")})
        monkeypatch.setattr(broker, "publish", lambda *a, **k: 1 / 0)
        hitoiki.emit("set_done", {})
    assert broker.drain(token) == []
    messages = [r.getMessage() for r in caplog.records]
    assert "didn't declare" in messages[0]
    assert "JSON can't hold" in messages[1] and "JSON can't hold" in messages[2]
    assert "Could not send" in messages[3]


def test_the_event_keeps_the_payload_as_emitted(hitoiki):
    token = broker.subscribe()
    payload = {"count": 1}
    hitoiki.emit("set_done", payload)
    payload["count"] = 2
    assert broker.drain(token)[0]["payload"] == {"count": 1}


def test_emit_from_another_thread(hitoiki):
    token = broker.subscribe()
    worker = threading.Thread(target=hitoiki.emit, args=("break_over",))
    worker.start()
    worker.join()
    event, = broker.drain(token)
    assert event["type"] == "addons.hitoiki.break_over" and event["payload"] is None


def test_an_old_handle_sends_for_the_provider_registered_again(hitoiki):
    # Tsunagi collects providers again on each profile open; a handle the add-on kept still works.
    actions.PROVIDERS.clear()
    Registry().provide("hitoiki", "Hitoiki", actions=[], events=[{"name": "set_done"}])
    token = broker.subscribe()
    hitoiki.emit("set_done", {})
    assert [e["type"] for e in broker.drain(token)] == [SET_DONE]


def test_declarations_are_checked(monkeypatch):
    monkeypatch.setattr(actions, "PROVIDERS", {})
    registry = Registry()
    with pytest.raises(ValueError, match="same name"):
        registry.provide("a", "A", actions=[], events=[{"name": "x"}, {"name": "x"}])
    with pytest.raises(ValueError, match="may only use"):
        registry.provide("b", "B", actions=[], events=[{"name": "Set-Done"}])
    registry.provide("c", "C", actions=[], events=[{"name": "x"}])
    assert actions.PROVIDERS["c"].addon_id == __name__.split(".")[0]
    assert actions.event_types() == {"addons.c.x"}
