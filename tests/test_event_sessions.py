"""Subscription boundaries and lifetime isolation, including suspended readers."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from anki.collection import OpChanges

from tsunagi.adapters.events import MAX_QUEUED, ApiOp, EventBroker, broker, dispatch_op
from tsunagi.http.v1.events import stream_events


@pytest.fixture(autouse=True)
def clean_broker():
    broker.reset()
    yield
    broker.reset()


def test_ready_captures_registration_boundary_without_becoming_a_notification():
    store = EventBroker()
    assert store.subscribe() is None
    session = store.start_session(object())
    store.publish("sync", phase="started")
    a = store.subscribe()
    store.publish("sync", phase="finished")
    b = store.subscribe()
    assert store.ready(a)["after_seq"] == 1
    assert store.ready(b)["after_seq"] == 2
    assert store.ready(a)["session_id"] == store.ready(b)["session_id"] == session
    assert store.ready(a)["refresh"] == ["collection"]
    assert "seq" not in store.ready(a)
    assert [e["seq"] for e in store.drain(a)] == [2]
    assert store.drain(b) == []


def test_overflow_preserves_boundary_and_uses_session_on_gap():
    session = broker.start_session(object())
    token = broker.subscribe()
    for i in range(MAX_QUEUED + 1):
        broker.publish("review", card_id=i, ease=3)
    assert broker.ready(token)["after_seq"] == 0
    event, = broker.drain(token)
    assert event["type"] == "gap"
    assert event["session_id"] == session
    assert event["after_seq"] == MAX_QUEUED + 1
    assert "seq" not in event


def test_reconnect_reuses_session_but_restart_permanently_closes_old_tokens():
    collection = object()
    old_session = broker.start_session(collection)
    old = broker.subscribe()
    broker.unsubscribe(old)
    old = broker.subscribe()
    assert broker.ready(old)["session_id"] == old_session
    broker.publish("review", card_id=1, ease=3)
    broker.begin_drain()
    new_session = broker.start_session(collection)
    new = broker.subscribe()
    assert new_session != old_session
    assert broker.ready(new)["after_seq"] == 0
    broker.begin_drain(old_session)  # old server thread finally exits
    assert not broker.is_draining(new)
    assert broker.is_draining(old)
    broker.publish("review", card_id=2, ease=3)
    assert broker.drain(old) == []
    assert broker.ready(old) is None
    assert broker.drain(new)[0]["card_id"] == 2


def test_old_collection_completion_cannot_publish_ids_in_new_profile():
    old_collection, new_collection = object(), object()
    old_op = ApiOp({"note_ids": [42]}, collection=old_collection)
    broker.start_session(new_collection)
    token = broker.subscribe()
    dispatch_op(OpChanges(note=True), old_op)
    assert broker.drain(token) == []
    # A late completion after a restart of the SAME collection is still useful.
    broker.start_session(old_collection)
    token = broker.subscribe()
    dispatch_op(OpChanges(note=True), old_op)
    assert broker.drain(token)[0]["targets"] == {"notes": [42]}


def test_payload_cannot_override_session_or_sequence():
    session = broker.start_session(object())
    token = broker.subscribe()
    broker.publish("sync", session_id="fake", seq=-1, ts=-1)
    event, = broker.drain(token)
    assert event["session_id"] == session
    assert event["seq"] == 1
    assert event["ts"] > 0


def test_inactive_session_returns_normal_unavailable_response(client):
    broker.begin_drain()
    response = client.get("/v1/events?timeout=0.1")
    assert response.status_code == 503


@pytest.mark.parametrize("transition", ["restart", "auth"])
def test_suspended_generator_discards_remaining_batch(transition, reset_settings):
    async def run():
        response = stream_events(timeout=5, max_events=None)
        gen = response.body_iterator
        await gen.__anext__()  # retry/comment
        ready_frame = await gen.__anext__()
        assert "event: refresh\n" in ready_frame
        assert "\nid:" not in ready_frame
        broker.publish("review", card_id=1, ease=3)
        broker.publish("review", card_id=2, ease=3)
        first = await gen.__anext__()
        assert '"card_id":1' in first
        if transition == "restart":
            broker.begin_drain()
            broker.start_session(object())
            broker.publish("review", card_id=3, ease=3)
            reason = "shutdown"
        else:
            reset_settings.update(api_key="rotated")
            reason = "auth"
        final = await gen.__anext__()
        assert "event: close" in final
        assert json.loads(final.split("data: ")[1])["reason"] == reason
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        assert not broker.has_subscribers()
    asyncio.run(run())


def test_shutdown_between_response_and_subscription_closes_without_ready():
    response = stream_events(timeout=5, max_events=None)
    broker.begin_drain()

    async def run():
        frames = [frame async for frame in response.body_iterator]
        assert len(frames) == 1
        assert "event: close" in frames[0]
        assert "shutdown" in frames[0]
    asyncio.run(run())


@pytest.mark.parametrize("failure", [RuntimeError, SystemExit])
def test_server_exit_closes_its_session_even_when_binding_fails(failure):
    from tsunagi.app import _serve

    session = broker.start_session(object())
    token = broker.subscribe()

    def fail():
        raise failure("bind failed")

    if failure is SystemExit:
        with pytest.raises(SystemExit):
            _serve(SimpleNamespace(run=fail), session)
    else:
        _serve(SimpleNamespace(run=fail), session)
    assert broker.is_draining(token)
    assert broker.subscribe() is None
