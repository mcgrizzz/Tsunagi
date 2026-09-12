"""Typing notifications stay bounded, ordered and isolated from collection writes."""
import asyncio
import json
from copy import deepcopy

import pytest

from tsunagi.adapters.events import MAX_QUEUED, ApiOp, EventBroker, broker, dispatch_op
from tsunagi.http.v1 import events as http_events


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(clock):
    instance = EventBroker(clock=clock)
    instance.start_session(object())
    return instance


def edit(nid=1, *, action="notes.updated", origin="ui", flags=None, **extra):
    return dict(origin=origin, action=action, targets={"notes": [nid]},
                refresh=["notes", "cards"],
                anki={"changes": flags or ["note", "note_text", "mtime"]}, **extra)


def test_short_pause_merges_all_targets_and_refresh_hints(store, clock):
    token = store.subscribe()
    first = edit(1)
    store.publish("change", **first)
    # The pending payload must not alias its producer's mutable lists.
    first["targets"]["notes"].append(999)
    clock.now = 0.2
    second = edit(2)
    second["targets"]["cards"] = [7]
    second["refresh"] = ["reviews"]
    store.publish("change", **second)
    clock.now = 0.499
    assert store.drain(token) == []
    clock.now = 0.5
    event, = store.drain(token)
    assert event["targets"] == {"notes": [1, 2], "cards": [7]}
    assert event["refresh"] == ["cards", "notes", "reviews"]
    assert event["action"] == "notes.updated"
    assert event["seq"] == 1


def test_continuous_typing_flushes_at_one_second_and_starts_a_new_burst(store, clock):
    token = store.subscribe()
    for step in range(10):
        clock.now = step / 10
        store.publish("change", **edit(step + 1))
        assert store.drain(token) == []
    clock.now = 1.0
    event, = store.drain(token)
    assert event["targets"]["notes"] == list(range(1, 11))
    store.publish("change", **edit(11))
    assert store.drain(token) == []
    clock.now = 1.3
    assert store.drain(token)[0]["targets"]["notes"] == [11]


def test_new_input_cannot_extend_an_expired_maximum(store, clock):
    token = store.subscribe()
    for step in range(11):
        clock.now = step / 10
        store.publish("change", **edit(step + 1))
    # No consumer ran during typing; publish still flushes the expired group.
    event, = store.drain(token)
    assert event["targets"]["notes"] == list(range(1, 11))
    clock.now = 1.3
    assert store.drain(token)[0]["targets"]["notes"] == [11]


def test_general_and_detailed_editor_notifications_share_timing_not_identity(store, clock):
    a, b = store.subscribe(), store.subscribe()
    for step in range(3):
        clock.now = step / 10
        general = edit(action="collection.changed")
        general["targets"] = {}
        store.publish("change", **general)
        store.publish("change", **edit(step + 1))
        assert store.drain(a) == store.drain(b) == []
    clock.now = 0.5
    events = store.drain(a)
    assert events == store.drain(b)
    assert [e["action"] for e in events] == ["collection.changed", "notes.updated"]
    assert [e["seq"] for e in events] == [1, 2]
    assert events[0]["targets"] == {}
    assert events[1]["targets"] == {"notes": [1, 2, 3]}
    # Previously returned events stay unchanged after later publication.
    saved = deepcopy(events)
    store.publish("change", **edit(4))
    clock.now = 0.8
    store.drain(a)
    assert events == saved


@pytest.mark.parametrize("type_,payload", [
    ("change", edit(origin="api")),
    ("change", edit(origin=None)),
    ("change", edit(action="notes.created")),
    ("change", edit(action="notes.deleted")),
    ("change", edit(action="collection.changed", flags=["note", "note_text", "card"])),
    ("change", edit(flags=["note", "note_text", "study_queues"])),
    ("change", edit(flags=["note", "note_text", "future_flag"])),
    ("change", edit(extra_metadata="unknown merge semantics")),
    ("review", {"card_id": 42, "ease": 3}),
    ("sync", {"phase": "started"}),
    ("reset", {}),
])
def test_other_activity_flushes_edits_before_immediate_notification(store, clock, type_, payload):
    token = store.subscribe()
    store.publish("change", **edit())
    clock.now = 0.1
    store.publish(type_, **payload)
    events = store.drain(token)
    assert len(events) == 2
    assert events[0]["action"] == "notes.updated"
    assert events[1]["type"] == type_
    assert events[0]["seq"] < events[1]["seq"]
    store.publish("change", **edit(2))
    assert store.drain(token) == []


def test_new_subscriber_boundary_excludes_older_pending_edits(store, clock):
    old = store.subscribe()
    store.publish("change", **edit(1))
    clock.now = 0.1
    new = store.subscribe()
    assert store.ready(new)["after_seq"] == 1
    assert store.drain(new) == []
    assert store.drain(old)[0]["targets"] == {"notes": [1]}
    store.publish("change", **edit(2))
    clock.now = 0.4
    assert store.drain(old) == store.drain(new)


def test_shutdown_and_old_collection_callbacks_cannot_cross_sessions(store, clock):
    old_collection = store._collection
    old = store.subscribe()
    old_session = store.ready(old)["session_id"]
    store.publish("change", **edit(1))
    store.begin_drain()
    store.start_session(object())
    new = store.subscribe()
    store.publish("change", collection=old_collection, **edit(2))
    store.publish("change", **edit(3))
    store.begin_drain(old_session)  # old thread finishing must leave the new burst alone
    clock.now = 0.3
    assert store.drain(old) == []
    assert store.drain(new)[0]["targets"] == {"notes": [3]}


def test_last_disconnect_discards_pending_edits_and_no_listener_keeps_no_batch(store):
    token = store.subscribe()
    store.publish("change", **edit(1))
    store.unsubscribe(token)
    assert store._pending_edits is None
    store.publish("change", **edit(2))
    assert store._pending_edits is None
    assert store.drain(store.subscribe()) == []


def test_pending_inputs_are_bounded_and_slow_subscribers_still_get_reset(store):
    token = store.subscribe()
    for _ in range(MAX_QUEUED):
        store.publish("change", **edit())
    assert store._pending_edits is None
    assert len(store.drain(token)) == 1
    for _ in range(MAX_QUEUED + 1):
        store.publish("change", **edit())
        store.publish("review", card_id=42, ease=3)
    event, = store.drain(token)
    assert event["type"] == "reset"
    assert event["reason"] == "lagged"
    assert event["refresh"] == ["collection"]


def test_real_anki_changes_debounce_updates_but_not_add_delete_or_undo(col, clock, monkeypatch):
    monkeypatch.setattr(broker, "_clock", clock)
    broker.reset()
    token = broker.subscribe()
    try:
        note = col.new_note(col.models.by_name("Basic"))
        note.fields = ["before", "back"]
        added = col.add_note(note, 1)
        dispatch_op(getattr(added, "changes", added), object())
        assert len(broker.drain(token)) == 1
        note.fields[0] = "after"
        updated = col.update_note(note)
        dispatch_op(updated, object())
        assert broker.drain(token) == []
        # The save itself has already completed and the live collection is current.
        assert col.get_note(note.id).fields[0] == "after"
        undone = col.undo()
        dispatch_op(getattr(undone, "changes", undone), None)
        assert len(broker.drain(token)) == 2
        assert col.get_note(note.id).fields[0] == "before"
        removed = col.remove_notes([note.id])
        dispatch_op(getattr(removed, "changes", removed), object())
        assert len(broker.drain(token)) == 1
        # Identical note flags from an API operation are never held.
        dispatch_op(updated, ApiOp())
        assert len(broker.drain(token)) == 1
    finally:
        broker.reset()


def test_http_wakes_for_quiet_deadline_and_counts_emitted_notifications(clock, monkeypatch):
    monkeypatch.setattr(broker, "_clock", clock)
    broker.reset()
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)
        clock.now += delay

    monkeypatch.setattr(http_events.asyncio, "sleep", sleep)

    async def run():
        gen = http_events.stream_events(timeout=None, max_events=1).body_iterator
        await gen.__anext__()  # retry/comment
        assert "event: ready" in await gen.__anext__()
        broker.publish("change", **edit(1))
        broker.publish("change", **edit(2))
        frame = await gen.__anext__()
        event = json.loads(frame.split("data: ")[1])
        assert event["targets"] == {"notes": [1, 2]}
        assert clock.now == pytest.approx(0.3)
        assert sleeps == pytest.approx([0.25, 0.05])
        assert '"reason": "max_events"' in await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    try:
        asyncio.run(run())
        assert not broker.has_subscribers()
    finally:
        broker.reset()


def test_auth_rotation_closes_without_releasing_pending_typing(clock, monkeypatch, reset_settings):
    monkeypatch.setattr(broker, "_clock", clock)
    broker.reset()

    async def run():
        gen = http_events.stream_events(timeout=None, max_events=None).body_iterator
        await gen.__anext__()
        await gen.__anext__()
        broker.publish("change", **edit())
        reset_settings.update(api_key="changed")
        clock.now = 1.0
        frame = await gen.__anext__()
        assert "event: close" in frame and '"reason": "auth"' in frame
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        assert broker._pending_edits is None

    try:
        asyncio.run(run())
    finally:
        broker.reset()
