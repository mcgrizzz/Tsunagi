"""Named data events, subscription boundaries and delivery gaps."""
import asyncio
import threading
import time

import pytest
from test_event_filters import event_broker as event_broker
from test_v1_events import parse_frames

from tsunagi.adapters.events import MAX_QUEUED
from tsunagi.http.v1.events import stream_events

pytestmark = pytest.mark.usefixtures("review_events")


async def open_stream(**params):
    options = {"timeout": None, "max_events": None, **params}
    stream = stream_events(**options).body_iterator
    assert ": connected" in await stream.__anext__()
    return stream


async def next_event(stream):
    frame = await stream.__anext__()
    (name, data), = parse_frames(frame)
    return name, data, frame


def test_notes_client_receives_queued_changes_after_ready(event_broker):
    async def consume():
        stream = await open_stream(resources="notes")
        try:
            # A change between subscription and initial delivery stays queued.
            event_broker.publish("change", affected=["notes", "cards"],
                                 targets={"notes": [42], "cards": [99]},
                                 origin="api", action="collection.changed",
                                 anki={"changes": ["note"]})
            name, initial, frame = await next_event(stream)
            assert name == "ready"
            assert initial["resources"] == ["notes"]
            assert initial["after_seq"] == 0
            assert "\nid:" not in frame

            name, change, _ = await next_event(stream)
            assert name == "notes.stale"
            assert "ids" not in change
            assert change["reason"] == "details_unavailable"
            assert "targets" not in change
            assert change["seq"] > initial["after_seq"]
            assert change["session_id"] == initial["session_id"]
            assert change["origin"] == "api"
            assert change["anki"] == {"changes": ["note"]}

            event_broker.publish("sync", phase="finished")
            event_broker.publish("cards.answered", card_id=1, ease=3)
            event_broker.publish("change", affected=["config"])
            event_broker.publish("reset")
            name, broad, _ = await next_event(stream)
            assert name == "notes.stale"
            assert broad["reason"] == "collection"
            assert "ids" not in broad
        finally:
            await stream.aclose()
        assert not event_broker.has_subscribers()

    asyncio.run(consume())


@pytest.mark.parametrize("type_,payload", [
    ("cards.answered", {"card_id": 42, "ease": 3}),
    ("sync", {"phase": "finished"}),
])
def test_action_only_clients_get_ready_without_data_notifications(event_broker, type_, payload):
    async def consume():
        stream = await open_stream(types=type_, max_events=1)
        name, ready, _ = await next_event(stream)
        assert name == "ready"
        assert ready["resources"] == []
        for _ in range(MAX_QUEUED + 1):
            event_broker.publish("reset")
            event_broker.publish("change", affected=["collection"])
        event_broker.publish(type_, **payload)
        name, event, _ = await next_event(stream)
        assert name == type_
        assert event.items() >= payload.items()
        assert (await next_event(stream))[:2] == ("close", {"reason": "max_events"})
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
        assert not event_broker.has_subscribers()

    asyncio.run(consume())


def test_resources_filter_each_named_change(event_broker):
    async def consume():
        stream = await open_stream(resources="notes,models")
        try:
            assert (await next_event(stream))[1]["resources"] == ["models", "notes"]
            event_broker.publish("change", affected=["notes", "cards"])
            assert (await next_event(stream))[0] == "notes.stale"
            event_broker.publish("change", targets={})  # unknown affected views
            assert (await next_event(stream))[0] == "models.stale"
            assert (await next_event(stream))[0] == "notes.stale"
        finally:
            await stream.aclose()

    asyncio.run(consume())


@pytest.mark.parametrize("types", ["change", "cards.answered", "change,cards.answered"])
def test_gap_reports_lost_messages_without_a_synthetic_data_change(event_broker, types):
    wants_data = "change" in types

    async def consume():
        stream = await open_stream(types=types, resources="notes" if wants_data else None,
                                   max_events=1)
        assert (await next_event(stream))[0] == "ready"
        for _ in range(MAX_QUEUED + 1):
            if wants_data:
                event_broker.publish("change", affected=["notes"])
            else:
                event_broker.publish("cards.answered", card_id=42, ease=3)
        name, gap, frame = await next_event(stream)
        assert name == "gap"
        assert gap["reason"] == "lagged"
        assert gap["discarded"] == MAX_QUEUED + 1
        assert gap["after_seq"] == MAX_QUEUED + 1
        assert "\nid:" not in frame
        # Neither ready nor gap consumes the limit. The next frame describes
        # this new operation, with no invented recovery/change frame in between.
        if wants_data:
            event_broker.publish("change", affected=["notes"],
                                 changes={"notes": {"updated": [99]}})
            name, update, _ = await next_event(stream)
            assert name == "notes.updated"
            assert update["ids"] == [99]
        else:
            event_broker.publish("cards.answered", card_id=99, ease=4)
            name, update, _ = await next_event(stream)
            assert name == "cards.answered"
            assert update["card_id"] == 99
        assert update["seq"] > gap["after_seq"]
        assert (await next_event(stream))[:2] == ("close", {"reason": "max_events"})
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    asyncio.run(consume())


@pytest.mark.parametrize("transition", ["restart", "auth"])
def test_gap_cannot_resume_a_closed_connection(event_broker, reset_settings, transition):
    async def consume():
        stream = await open_stream(resources="notes")
        await next_event(stream)  # ready
        for _ in range(MAX_QUEUED + 1):
            event_broker.publish("change", affected=["notes"])
        assert (await next_event(stream))[0] == "gap"
        if transition == "restart":
            event_broker.start_session(object())
            reason = "shutdown"
        else:
            reset_settings.update(no_key_local_role="read_only")
            reason = "auth"
        assert (await next_event(stream))[:2] == ("close", {"reason": reason})
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
        assert not event_broker.has_subscribers()

    asyncio.run(consume())


@pytest.mark.parametrize("types", ["cards.answered", "sync", "cards.answered,sync", "cards.updated"])
def test_resource_filter_cannot_silently_do_nothing(client, event_broker, types):
    response = client.get("/v1/events", params={"types": types, "resources": "notes"})
    assert response.status_code == 422
    assert response.json()["detail"] == "types must match at least one selected data resource"
    assert not event_broker.has_subscribers()


def test_publish_from_another_thread_wakes_the_stream(event_broker):
    """Hooks publish on Anki's main thread; the stream must not wait to poll."""
    async def consume():
        stream = await open_stream(resources="notes")
        try:
            assert (await next_event(stream))[0] == "ready"
            published = []

            def publish():
                published.append(time.monotonic())
                event_broker.publish("change", affected=["notes"])

            threading.Timer(0.05, publish).start()
            name, _, _ = await next_event(stream)
            return name, time.monotonic() - published[0]
        finally:
            await stream.aclose()

    name, latency = asyncio.run(consume())
    assert name == "notes.stale"
    assert latency < 0.05  # the old 250 ms poll averaged far more
