"""Subscription interests must reduce traffic without hiding invalidations."""
import asyncio
from types import SimpleNamespace

import pytest
from test_v1_events import parse_frames

from tsunagi.adapters.events import MAX_QUEUED, EventBroker
from tsunagi.http.v1 import events as http_events


@pytest.fixture
def event_broker(monkeypatch):
    broker = EventBroker()
    broker.start_session(object())
    monkeypatch.setattr(http_events, "broker", broker)
    return broker


def subscribe(broker, *, types=None, resources=None):
    return broker.subscribe(
        types=frozenset(types) if types is not None else None,
        resources=frozenset(resources) if resources is not None else None,
    )


def test_independent_interests_share_event_ids_and_allow_sequence_gaps(event_broker):
    all_events = subscribe(event_broker)
    notes = subscribe(event_broker, types={"change"}, resources={"notes"})
    cards = subscribe(event_broker, types={"change"}, resources={"cards"})
    reviews = subscribe(event_broker, types={"review"})

    event_broker.publish("change", refresh=["notes", "cards"], targets={})
    event_broker.publish("review", card_id=42, ease=3)
    event_broker.publish("change", refresh=["config"])
    event_broker.publish("change", refresh=["notes"])

    everything = event_broker.drain(all_events)
    assert event_broker.drain(notes) == [everything[0], everything[3]]
    assert event_broker.drain(cards) == [everything[0]]
    assert event_broker.drain(reviews) == [everything[1]]
    assert [event["seq"] for event in everything] == [1, 2, 3, 4]


@pytest.mark.parametrize("payload", [
    {"refresh": ["collection"]},
    {"refresh": []},
    {},
    # A deck edit can affect which notes match an Anki search. Target IDs
    # are hints about the operation, not the complete set of affected views.
    {"refresh": ["decks", "notes"], "targets": {"decks": [9]}},
])
def test_broad_unknown_and_related_changes_reach_note_clients(event_broker, payload):
    notes = subscribe(event_broker, types={"change"}, resources={"notes"})
    event_broker.publish("change", **payload)
    assert [event["type"] for event in event_broker.drain(notes)] == ["change"]


def test_resource_interests_filter_changes_and_types_select_other_notifications(event_broker):
    token = subscribe(event_broker, resources={"notes"})
    event_broker.publish("change", refresh=["config"])
    event_broker.publish("review", card_id=42, ease=3)
    event_broker.publish("sync", phase="started")
    assert [event["type"] for event in event_broker.drain(token)] == ["review", "sync"]

    token = subscribe(event_broker, types={"sync"}, resources={"notes"})
    event_broker.publish("change", refresh=["collection"])
    event_broker.publish("sync", phase="finished")
    event_broker.publish("reset")
    assert [event["type"] for event in event_broker.drain(token)] == ["sync", "reset"]


def test_unrelated_traffic_cannot_overflow_filtered_queue(event_broker):
    unfiltered = subscribe(event_broker)
    filtered = subscribe(event_broker, types={"change"}, resources={"notes"})
    event_broker.publish("change", refresh=["notes"], targets={"notes": [42]})
    for _ in range(MAX_QUEUED * 2):
        event_broker.publish("review", card_id=9, ease=3)
        event_broker.publish("change", refresh=["config"])

    kept = event_broker.drain(filtered)
    assert len(kept) == 1
    assert kept[0]["targets"] == {"notes": [42]}
    assert event_broker.drain(unfiltered)[0]["reason"] == "lagged"


def test_matching_traffic_still_overflows_to_mandatory_reset(event_broker):
    token = subscribe(event_broker, types={"review"})
    for _ in range(MAX_QUEUED + 1):
        event_broker.publish("review", card_id=42, ease=3)
    assert event_broker.ready(token)["type"] == "ready"
    reset, = event_broker.drain(token)
    assert reset["type"] == "reset"
    assert reset["reason"] == "lagged"
    assert reset["refresh"] == ["collection"]
    assert event_broker.drain(token) == []


def test_debounced_edits_keep_ids_and_respect_each_subscription():
    clock = SimpleNamespace(now=0.0)
    broker = EventBroker(clock=lambda: clock.now)
    broker.start_session(object())
    notes = subscribe(broker, types={"change"}, resources={"notes"})
    config = subscribe(broker, types={"change"}, resources={"config"})
    all_events = subscribe(broker)
    for note_id in [10, 20]:
        broker.publish("change", origin="ui", action="notes.updated",
                       targets={"notes": [note_id]}, refresh=["notes", "cards"],
                       anki={"changes": ["note", "note_text"]})
        clock.now += 0.1
    assert broker.drain(notes) == []
    clock.now = 0.4
    merged = broker.drain(notes)
    assert len(merged) == 1
    assert merged[0]["targets"] == {"notes": [10, 20]}
    assert broker.drain(all_events) == merged
    assert broker.drain(config) == []

    # A filtered-out review is still an ordering barrier for pending edits.
    broker.publish("change", origin="ui", action="notes.updated",
                   targets={"notes": [30]}, refresh=["notes"],
                   anki={"changes": ["note", "note_text"]})
    broker.publish("review", card_id=42, ease=3)
    assert [e["type"] for e in broker.drain(notes)] == ["change"]
    assert [e["type"] for e in broker.drain(all_events)] == ["change", "review"]


def test_filtered_subscriptions_do_not_cross_ready_or_session_boundaries(event_broker):
    token = subscribe(event_broker, types={"change"}, resources={"notes"})
    event_broker.publish("change", origin="ui", action="notes.updated",
                         targets={"notes": [42]}, refresh=["notes"],
                         anki={"changes": ["note", "note_text"]})
    next_token = subscribe(event_broker, types={"review"})
    prior, = event_broker.drain(token)
    assert event_broker.ready(next_token)["after_seq"] == prior["seq"]
    assert event_broker.drain(next_token) == []
    old_session = event_broker.ready(token)["session_id"]
    event_broker.start_session(object())
    assert event_broker.is_draining(token)
    fresh = subscribe(event_broker, types={"sync"})
    event_broker.publish("sync", phase="started")
    assert event_broker.drain(token) == []
    assert event_broker.drain(next_token) == []
    assert event_broker.drain(fresh)[0]["session_id"] != old_session


@pytest.mark.parametrize("query", [
    "types=", "types=CHANGE", "types=change,", "types=changed",
    "types=reset", "resources=", "resources=note", "resources=notes,,cards",
])
def test_bad_filters_fail_before_opening_stream(client, event_broker, query):
    response = client.get("/v1/events?" + query)
    assert response.status_code == 422
    assert "comma-separated list" in response.json()["detail"]
    assert not event_broker.has_subscribers()


def test_http_filters_parse_lists_and_count_only_delivered_events(client, event_broker,
                                                                 monkeypatch):
    original = event_broker.subscribe

    def with_events(**kwargs):
        token = original(**kwargs)
        event_broker.publish("review", card_id=42, ease=3)
        event_broker.publish("change", refresh=["config"])
        event_broker.publish("change", refresh=["notes"])
        event_broker.publish("change", refresh=["cards"])
        event_broker.publish("sync", phase="started")
        event_broker.publish("reset")
        return token

    monkeypatch.setattr(event_broker, "subscribe", with_events)
    response = client.get("/v1/events", params={
        "types": " change, sync,change ", "resources": "notes, cards",
        "max_events": 4, "timeout": 2,
    })
    assert response.status_code == 200
    frames = parse_frames(response.text)
    assert [name for name, _ in frames] == ["ready", "change", "change", "sync",
                                          "reset", "close"]
    assert [event["seq"] for _, event in frames[1:-1]] == [3, 4, 5, 6]
    assert frames[-1][1] == {"reason": "max_events"}
    assert not event_broker.has_subscribers()


@pytest.mark.parametrize("reason", ["auth", "shutdown"])
def test_filtered_streams_keep_close_controls(event_broker, reset_settings, reason):
    async def consume():
        response = http_events.stream_events(
            timeout=None, max_events=None, types="review", resources="notes")
        stream = response.body_iterator
        await stream.__anext__()  # connection comment
        ready = parse_frames(await stream.__anext__())
        assert ready[0][0] == "ready"
        if reason == "auth":
            reset_settings.update(api_key="changed")
        else:
            event_broker.begin_drain()
        assert parse_frames(await stream.__anext__()) == [("close", {"reason": reason})]
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
        assert not event_broker.has_subscribers()

    asyncio.run(consume())


def test_openapi_explains_subscription_filters(client):
    operation = client.get("/openapi.json").json()["paths"]["/v1/events"]["get"]
    parameters = {param["name"]: param for param in operation["parameters"]}
    for name in ("types", "resources"):
        assert parameters[name]["in"] == "query"
        assert not parameters[name]["required"]
        assert "comma-separated" in parameters[name]["description"]
