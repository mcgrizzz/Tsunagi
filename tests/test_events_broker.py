"""
Unit tests for the event broker and the OpChanges dispatch rules. The broker
is pure stdlib; dispatch_op is exercised with real anki OpChanges protos
(the genuine anki package is a test dependency).
"""
import pytest
from anki.collection import OpChanges

from tsunagi.adapters.events import (
    API_INITIATOR,
    MAX_QUEUED,
    EventBroker,
    broker,
    dispatch_op,
    publish_review,
    publish_sync,
)


@pytest.fixture()
def store():
    return EventBroker()


@pytest.fixture(autouse=True)
def clean_singleton():
    broker.reset()
    yield
    broker.reset()


class TestBroker:
    def test_publish_fans_out_to_every_subscriber(self, store):
        a, b = store.subscribe(), store.subscribe()
        store.publish("sync", phase="started")
        got_a, got_b = store.drain(a), store.drain(b)
        assert got_a == got_b
        assert got_a[0]["type"] == "sync"
        assert got_a[0]["phase"] == "started"

    def test_seq_is_monotonic_and_shared(self, store):
        token = store.subscribe()
        store.publish("sync", phase="started")
        store.publish("sync", phase="finished")
        seqs = [e["seq"] for e in store.drain(token)]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == 2

    def test_events_carry_a_timestamp(self, store):
        token = store.subscribe()
        store.publish("review", card_id=1, ease=3)
        assert store.drain(token)[0]["ts"] > 0

    def test_drain_empties_the_queue(self, store):
        token = store.subscribe()
        store.publish("review", card_id=1, ease=3)
        assert len(store.drain(token)) == 1
        assert store.drain(token) == []

    def test_subscriber_only_sees_events_after_subscribing(self, store):
        store.publish("review", card_id=1, ease=3)
        token = store.subscribe()
        assert store.drain(token) == []

    def test_overflow_drops_oldest_and_synthesizes_lagged_reset(self, store):
        token = store.subscribe()
        for i in range(MAX_QUEUED + 5):
            store.publish("review", card_id=i, ease=1)
        events = store.drain(token)
        assert events[0] == {**events[0], "type": "reset", "reason": "lagged"}
        assert len(events) == MAX_QUEUED + 1
        # The oldest five were dropped; the newest survives.
        assert events[-1]["card_id"] == MAX_QUEUED + 4
        assert events[1]["card_id"] == 5
        # The lag was reported once; the next drain is clean.
        store.publish("review", card_id=99, ease=1)
        assert [e["type"] for e in store.drain(token)] == ["review"]

    def test_unsubscribe_stops_delivery(self, store):
        token = store.subscribe()
        store.unsubscribe(token)
        store.publish("sync", phase="started")
        assert store.drain(token) == []

    def test_drain_flag(self, store):
        assert store.is_draining() is False
        store.begin_drain()
        assert store.is_draining() is True
        store.end_drain()
        assert store.is_draining() is False

    def test_reset_drops_everything(self, store):
        token = store.subscribe()
        store.publish("sync", phase="started")
        store.begin_drain()
        store.reset()
        assert store.drain(token) == []
        assert store.is_draining() is False


def op_changes(**flags):
    changes = OpChanges()
    for name, value in flags.items():
        setattr(changes, name, value)
    return changes


def all_true_changes():
    changes = OpChanges()
    for field in changes.DESCRIPTOR.fields:
        if field.name != "kind":
            setattr(changes, field.name, True)
    return changes


class TestDispatchOp:
    def drain_one(self):
        token = broker.subscribe()
        return token

    def test_blank_changes_are_dropped(self):
        token = broker.subscribe()
        # Tsunagi ops whose backend call returns no OpChanges fabricate a
        # blank one - indistinguishable from a no-op, so no event.
        dispatch_op(OpChanges(), None)
        assert broker.drain(token) == []

    def test_all_true_without_handler_is_a_reset(self):
        token = broker.subscribe()
        dispatch_op(all_true_changes(), None)
        events = broker.drain(token)
        assert [e["type"] for e in events] == ["reset"]
        assert "changes" not in events[0]

    def test_all_true_with_a_handler_is_still_an_op(self):
        # Only Anki's synthesized firehose has handler=None; a real op that
        # happens to touch everything keeps its identity.
        token = broker.subscribe()
        dispatch_op(all_true_changes(), object())
        assert [e["type"] for e in broker.drain(token)] == ["op"]

    def test_api_origin(self):
        token = broker.subscribe()
        dispatch_op(op_changes(card=True, study_queues=True), API_INITIATOR)
        event = broker.drain(token)[0]
        assert event["type"] == "op"
        assert event["origin"] == "api"
        assert sorted(event["changes"]) == ["card", "study_queues"]

    def test_ui_origin(self):
        token = broker.subscribe()
        dispatch_op(op_changes(note=True), object())
        assert broker.drain(token)[0]["origin"] == "ui"

    def test_null_origin(self):
        token = broker.subscribe()
        dispatch_op(op_changes(deck=True), None)
        assert broker.drain(token)[0]["origin"] is None


class TestApiInitiatorTagging:
    def test_collection_op_call_tags_the_api_sentinel(self, col, monkeypatch):
        # Every Tsunagi mutation must pass API_INITIATOR so its op event
        # carries origin "api" (the fake CollectionOp records the kwarg).
        from tsunagi.adapters import ops
        created = []
        real = ops.CollectionOp

        def recording(**kwargs):
            op = real(**kwargs)
            created.append(op)
            return op

        monkeypatch.setattr(ops, "CollectionOp", recording)
        assert ops.collection_op_call(lambda c: 42) == 42
        assert created[0].initiator is API_INITIATOR


class TestPublishHelpers:
    def test_review(self):
        token = broker.subscribe()
        publish_review(1690000000000, 3)
        event = broker.drain(token)[0]
        assert event["type"] == "review"
        assert event["card_id"] == 1690000000000
        assert event["ease"] == 3

    def test_sync(self):
        token = broker.subscribe()
        publish_sync("finished")
        assert broker.drain(token)[0]["phase"] == "finished"
