"""
Unit tests for the event broker and the OpChanges dispatch rules. The broker
is pure stdlib; dispatch_op is exercised with real anki OpChanges protos
(the genuine anki package is a test dependency).
"""
import pytest
from anki.collection import OpChanges

from tsunagi.adapters.events import (
    MAX_QUEUED,
    ApiOp,
    EventBroker,
    broker,
    dispatch_op,
    publish_review,
    publish_sync,
)


@pytest.fixture()
def store():
    store = EventBroker()
    store.start_session(object())
    return store


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

    def test_overflow_discards_incomplete_backlog_and_reports_gap(self, store):
        token = store.subscribe()
        for i in range(MAX_QUEUED + 5):
            store.publish("review", card_id=i, ease=1)
        events = store.drain(token)
        assert events[0] == {**events[0], "type": "gap", "reason": "lagged"}
        assert len(events) == 1
        assert events[0]["discarded"] == MAX_QUEUED + 5
        gap_boundary = events[0]["after_seq"]
        # The lag was reported once; the next drain is clean.
        store.publish("review", card_id=99, ease=1)
        following = store.drain(token)
        assert [e["type"] for e in following] == ["review"]
        assert following[0]["seq"] > gap_boundary

    def test_unsubscribe_stops_delivery(self, store):
        token = store.subscribe()
        store.unsubscribe(token)
        store.publish("sync", phase="started")
        assert store.drain(token) == []

    def test_has_subscribers(self, store):
        assert store.has_subscribers() is False
        token = store.subscribe()
        assert store.has_subscribers() is True
        store.unsubscribe(token)
        assert store.has_subscribers() is False

    def test_drain_flag(self, store):
        assert store.is_draining() is False
        store.begin_drain()
        assert store.is_draining() is True
        store.start_session(object())
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
        assert [e["type"] for e in broker.drain(token)] == ["change"]

    def test_api_origin(self):
        token = broker.subscribe()
        dispatch_op(op_changes(card=True, study_queues=True), ApiOp())
        event = broker.drain(token)[0]
        assert event["type"] == "change"
        assert event["origin"] == "api"
        assert sorted(event["anki"]["changes"]) == ["card", "study_queues"]

    def test_api_details_are_merged_into_the_event(self):
        token = broker.subscribe()
        dispatch_op(op_changes(note=True), ApiOp({"note_ids": [42, 43]}))
        event = broker.drain(token)[0]
        assert event["origin"] == "api"
        assert event["targets"]["notes"] == [42, 43]

    def test_api_details_cannot_clobber_core_keys(self):
        token = broker.subscribe()
        dispatch_op(op_changes(note=True),
                    ApiOp({"origin": "spoofed", "changes": [], "seq": -1}))
        event = broker.drain(token)[0]
        assert event["origin"] == "api"
        assert event["anki"]["changes"] == ["note"]
        assert event["seq"] > 0

    def test_ui_origin(self):
        token = broker.subscribe()
        dispatch_op(op_changes(note=True), object())
        assert broker.drain(token)[0]["origin"] == "ui"

    def test_null_origin(self):
        token = broker.subscribe()
        dispatch_op(op_changes(deck=True), None)
        assert broker.drain(token)[0]["origin"] is None

    def test_undo_does_not_inherit_the_next_undoable_actions_label(self):
        # Observed after undoing Card Batch: Anki supplies no handler, and
        # undo_status().undo now names the earlier Update Deck operation.
        token = broker.subscribe()
        dispatch_op(op_changes(card=True, study_queues=True), None,
                    label="Update Deck")
        events = broker.drain(token)
        assert len(events) == 1
        assert events[0]["type"] == "change"
        assert events[0]["origin"] is None
        assert sorted(events[0]["anki"]["changes"]) == ["card", "study_queues"]
        assert "label" not in events[0]["anki"]

    def test_identified_api_operation_keeps_its_label(self):
        token = broker.subscribe()
        dispatch_op(op_changes(card=True), ApiOp({"card_ids": [42]}),
                    label="Suspend")
        event = broker.drain(token)[0]
        assert event["anki"]["label"] == "Suspend"
        assert event["origin"] == "api"
        assert event["targets"]["cards"] == [42]

    def test_label_is_carried_when_known(self):
        token = broker.subscribe()
        dispatch_op(op_changes(note=True), object(), label="Update Note")
        assert broker.drain(token)[0]["anki"]["label"] == "Update Note"

    def test_label_is_omitted_when_unknown(self):
        token = broker.subscribe()
        dispatch_op(op_changes(note=True), object())
        dispatch_op(op_changes(note=True), object(), label="")
        for event in broker.drain(token):
            assert "label" not in event["anki"]


@pytest.fixture()
def recorded_ops(monkeypatch):
    from tsunagi.adapters import ops
    created = []
    real = ops.CollectionOp

    def recording(**kwargs):
        op = real(**kwargs)
        created.append(op)
        return op

    monkeypatch.setattr(ops, "CollectionOp", recording)
    return created


class TestApiInitiatorTagging:
    def test_collection_op_call_tags_an_api_op(self, col, recorded_ops):
        # Every Tsunagi mutation must pass an ApiOp initiator so its op
        # event carries origin "api" (the fake CollectionOp records it).
        from tsunagi.adapters import ops
        assert ops.collection_op_call(lambda c: 42) == 42
        assert isinstance(recorded_ops[0].initiator, ApiOp)
        assert recorded_ops[0].initiator.details == {}

    def test_adapter_event_details_reach_the_initiator(self, col, recorded_ops):
        # delete on ids that don't exist still runs the op - the plumbing is
        # what's under test: the decorator's event_details land on the ApiOp.
        from tsunagi.adapters.anki.notes import delete_notes
        assert delete_notes([123, 456]) == 0
        assert recorded_ops[0].initiator.details == {"note_ids": [123, 456]}

    def test_answer_cards_carries_card_ids(self, col, recorded_ops):
        # Missing ids report False but the op still ran - and tagged itself.
        from tsunagi.adapters.anki.cards import answer_cards
        assert answer_cards([{"card_id": 123, "ease": 3}]) == [False]
        assert recorded_ops[0].initiator.details == {"card_ids": [123]}


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


class TestRealChangesPropagation:
    """
    Mutation adapters return ValueWithChanges so the op reports the backend's
    REAL OpChanges - the difference between Anki's browser repainting (and an
    event firing) after an API write, and a fabricated blank that reports
    nothing changed.
    """

    def _card_id(self, col):
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = "x"
        col.add_note(note, 1)
        return int(col.card_ids_of_note(note.id)[0])

    def test_value_with_changes_unwraps_wrapper_protos(self):
        from anki.collection import OpChanges, OpChangesWithCount

        from tsunagi.adapters.ops import ValueWithChanges
        wrapped = OpChangesWithCount(count=3)
        wrapped.changes.card = True
        v = ValueWithChanges([True], wrapped)
        assert isinstance(v.changes, OpChanges)
        assert v.changes.card is True

    def test_suspend_reports_card_and_queue_changes(self, col, recorded_ops):
        from tsunagi.adapters.anki.cards import suspend_cards
        cid = self._card_id(col)
        assert suspend_cards([cid]) == 1          # caller value unchanged
        changes = recorded_ops[-1].result.changes
        assert changes.card is True
        assert changes.study_queues is True

    def test_delete_notes_reports_note_changes(self, col, recorded_ops):
        from tsunagi.adapters.anki.notes import delete_notes
        cid = self._card_id(col)
        nid = int(col.db.scalar("select nid from cards where id = ?", cid))
        assert delete_notes([nid]) == 1
        assert recorded_ops[-1].result.changes.note is True

    def test_noop_still_reports_blank(self, col, recorded_ops):
        # A batch where nothing was written keeps the blank-changes shape, so
        # the event stream correctly stays silent.
        from tsunagi.adapters.anki.cards import set_ease_factors
        assert set_ease_factors([{"id": 999999, "factor": 2500}]) == [False]
        changes = recorded_ops[-1].result.changes
        assert not any(getattr(changes, f.name) for f in changes.DESCRIPTOR.fields)


class TestEventDetailsCoverage:
    """The scheduling verbs and deck mutations tag their op events with ids."""

    def _card_id(self, col):
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = "x"
        col.add_note(note, 1)
        return int(col.card_ids_of_note(note.id)[0])

    def test_suspend_carries_card_ids(self, col, recorded_ops):
        from tsunagi.adapters.anki.cards import suspend_cards
        cid = self._card_id(col)
        suspend_cards([cid])
        assert recorded_ops[-1].initiator.details == {"card_ids": [cid]}

    def test_set_ease_carries_card_ids(self, col, recorded_ops):
        from tsunagi.adapters.anki.cards import set_ease_factors
        set_ease_factors([{"id": 123, "factor": 2500}])
        assert recorded_ops[-1].initiator.details == {"card_ids": [123]}

    def test_patch_deck_carries_deck_ids(self, col, recorded_ops):
        from tsunagi.adapters.anki.decks import patch_deck
        patch_deck(1, {"desc": "hello"})
        assert recorded_ops[-1].initiator.details == {"deck_ids": [1]}

    def test_batch_carries_the_union(self, col, recorded_ops):
        from tsunagi.adapters.anki.cards import batch_cards
        from tsunagi.shared.schemas.cards import CardIds, SetFlagRequest
        c1, c2 = self._card_id(col), self._card_id(col)
        result = batch_cards([
            ("suspend", CardIds(card_ids=[c1])),
            ("set-flag", SetFlagRequest(card_ids=[c1, c2], flag=1)),
        ])
        assert result["affected"] == 3
        assert recorded_ops[-1].initiator.details == {"card_ids": [c1, c2]}
        # And the merged proto reports real flags for the event stream.
        assert recorded_ops[-1].result.changes.card is True
