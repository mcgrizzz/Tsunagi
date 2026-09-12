"""Public refresh subscriptions and delivery failures have different jobs."""
import asyncio

import pytest
from test_event_filters import event_broker as event_broker
from test_v1_events import parse_frames

from tsunagi.adapters.events import MAX_QUEUED
from tsunagi.http.v1.events import stream_events


async def open_stream(**params):
    options = {"timeout": None, "max_events": None, **params}
    stream = stream_events(**options).body_iterator
    assert ": connected" in await stream.__anext__()
    return stream


async def next_event(stream):
    frame = await stream.__anext__()
    (name, data), = parse_frames(frame)
    return name, data, frame


def test_notes_client_needs_one_handler_for_initial_change_and_collection(event_broker):
    async def consume():
        stream = await open_stream(resources="notes")
        try:
            # A change between subscription and initial delivery stays queued.
            event_broker.publish("change", refresh=["notes", "cards"],
                                 targets={"notes": [42], "cards": [99]},
                                 origin="api", action="collection.changed",
                                 anki={"changes": ["note"]})
            name, initial, frame = await next_event(stream)
            assert name == "refresh"
            assert initial["reason"] == "initial"
            assert initial["resources"] == ["notes"]
            assert initial["targets"] == {}
            assert initial["after_seq"] == 0
            assert "\nid:" not in frame

            name, change, _ = await next_event(stream)
            assert name == "refresh"
            assert change["reason"] == "change"
            assert change["resources"] == ["notes"]
            assert change["targets"] == {"notes": [42]}
            assert change["seq"] > initial["after_seq"]
            assert change["session_id"] == initial["session_id"]
            assert change["origin"] == "api"
            assert change["anki"] == {"changes": ["note"]}

            event_broker.publish("sync", phase="finished")
            event_broker.publish("review", card_id=1, ease=3)
            event_broker.publish("change", refresh=["config"])
            event_broker.publish("reset")
            name, broad, _ = await next_event(stream)
            assert name == "refresh"
            assert broad["reason"] == "collection"
            assert broad["resources"] == ["notes"]
            assert broad["targets"] == {}
        finally:
            await stream.aclose()
        assert not event_broker.has_subscribers()

    asyncio.run(consume())


@pytest.mark.parametrize("type_,payload", [
    ("review", {"card_id": 42, "ease": 3}),
    ("sync", {"phase": "finished"}),
])
def test_action_only_clients_receive_no_initial_or_broad_refresh(event_broker, type_, payload):
    async def consume():
        stream = await open_stream(types=type_, max_events=1)
        for _ in range(MAX_QUEUED + 1):
            event_broker.publish("reset")
            event_broker.publish("change", refresh=["collection"])
        event_broker.publish(type_, **payload)
        name, event, _ = await next_event(stream)
        assert name == type_
        assert event.items() >= payload.items()
        assert (await next_event(stream))[:2] == ("close", {"reason": "max_events"})
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
        assert not event_broker.has_subscribers()

    asyncio.run(consume())


def test_refresh_resources_are_intersected_with_each_change(event_broker):
    async def consume():
        stream = await open_stream(resources="notes,models")
        try:
            assert (await next_event(stream))[1]["resources"] == ["models", "notes"]
            event_broker.publish("change", refresh=["notes", "cards"])
            assert (await next_event(stream))[1]["resources"] == ["notes"]
            event_broker.publish("change", targets={})  # unknown affected views
            assert (await next_event(stream))[1]["resources"] == ["models", "notes"]
        finally:
            await stream.aclose()

    asyncio.run(consume())


@pytest.mark.parametrize("types", ["refresh", "review", "refresh,review"])
def test_delivery_gap_and_data_recovery_are_separate(event_broker, types):
    wants_refresh = "refresh" in types

    async def consume():
        stream = await open_stream(types=types, resources="notes" if wants_refresh else None,
                                   max_events=1)
        if wants_refresh:
            assert (await next_event(stream))[1]["reason"] == "initial"
        for _ in range(MAX_QUEUED + 1):
            if wants_refresh:
                event_broker.publish("change", refresh=["notes"])
            else:
                event_broker.publish("review", card_id=42, ease=3)
        name, gap, frame = await next_event(stream)
        assert name == "gap"
        assert gap["reason"] == "lagged"
        assert gap["discarded"] == MAX_QUEUED + 1
        assert gap["after_seq"] == MAX_QUEUED + 1
        assert "\nid:" not in frame
        assert "resources" not in gap
        if wants_refresh:
            name, recovery, frame = await next_event(stream)
            assert name == "refresh"
            assert recovery["reason"] == "recovery"
            assert recovery["resources"] == ["notes"]
            assert recovery["after_seq"] == gap["after_seq"]
            assert recovery["targets"] == {}
            assert "\nid:" not in frame
        else:
            # The gap does not exhaust max_events, and recovery does not
            # invent a refresh requirement for a client reacting to answers.
            event_broker.publish("review", card_id=99, ease=4)
            name, review, _ = await next_event(stream)
            assert name == "review"
            assert review["card_id"] == 99
            assert review["seq"] > gap["after_seq"]
        assert (await next_event(stream))[:2] == ("close", {"reason": "max_events"})
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    asyncio.run(consume())


@pytest.mark.parametrize("transition", ["restart", "auth"])
def test_gap_cannot_release_recovery_from_old_connection(event_broker, reset_settings, transition):
    async def consume():
        stream = await open_stream(resources="notes")
        await next_event(stream)  # initial refresh
        for _ in range(MAX_QUEUED + 1):
            event_broker.publish("change", refresh=["notes"])
        assert (await next_event(stream))[0] == "gap"
        if transition == "restart":
            event_broker.start_session(object())
            reason = "shutdown"
        else:
            reset_settings.update(api_key="rotated")
            reason = "auth"
        assert (await next_event(stream))[:2] == ("close", {"reason": reason})
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
        assert not event_broker.has_subscribers()

    asyncio.run(consume())


@pytest.mark.parametrize("types", ["review", "sync", "review,sync"])
def test_resource_filter_cannot_silently_do_nothing(client, event_broker, types):
    response = client.get("/v1/events", params={"types": types, "resources": "notes"})
    assert response.status_code == 422
    assert response.json()["detail"] == "resources requires the refresh event type"
    assert not event_broker.has_subscribers()
