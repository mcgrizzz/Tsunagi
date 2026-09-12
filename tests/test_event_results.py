"""Completed mutation data, without extra collection reads or rendering."""
import pytest
from anki.collection import OpChanges
from test_events_broker import recorded_ops as recorded_ops

from tsunagi.adapters import ops
from tsunagi.adapters.anki import cards, notes
from tsunagi.adapters.event_results import (
    MAX_RESULT_BYTES,
    MAX_RESULT_IDS,
    freeze_changes,
)
from tsunagi.adapters.events import broker, dispatch_op
from tsunagi.http.v1.events import _change_event
from tsunagi.shared.errors import ResourceNotFoundError


@pytest.fixture
def subscription(col):
    broker.start_session(col)
    token = broker.subscribe(types={"change"})
    yield token
    broker.begin_drain()


def emit_last(recorded_ops, subscription, resources=("notes", "cards")):
    op = recorded_ops[-1]
    dispatch_op(op.result.changes, op.initiator)
    emitted = broker.drain(subscription)
    assert len(emitted) == 1
    return _change_event(emitted[0], frozenset(resources))


def new_note():
    return notes.create_note({"modelName": "Basic", "deckName": "Default",
                              "fields": {"Front": "word", "Back": "meaning"}})


def test_create_reuses_persisted_result_without_subscriber_reads(col, subscription, recorded_ops, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("event construction must not load a note or render a card")

    get_note = col.get_note
    reads = []
    def counted(nid):
        reads.append(nid)
        return get_note(nid)
    monkeypatch.setattr(col, "get_note", counted)
    monkeypatch.setattr(col, "get_card", unexpected)
    broker.subscribe(types={"change"})
    saved = new_note()
    assert reads == [saved.id]  # one authoritative save result, shared by subscribers
    event = emit_last(recorded_ops, subscription)
    assert event["changes"]["notes"]["upsert"] == [saved.dict()]
    assert event["changes"]["cards"]["fetch"] == saved.cards
    assert event["refresh"] == []
    # Result objects may be changed by a caller after success. Queued events cannot.
    saved.tags.append("after-return")
    assert event["changes"]["notes"]["upsert"][0]["tags"] == []


def test_patch_returns_saved_fields_and_tags(col, subscription, recorded_ops):
    saved = new_note()
    col.db.execute("update notes set mod = 1 where id = ?", saved.id)
    updated = notes.patch_note(saved.id, {"fields": {"Front": "changed"},
                                          "tags": ["zebra", "Alpha", "Alpha"]})
    event = emit_last(recorded_ops, subscription, ("notes",))
    snapshot = event["changes"]["notes"]["upsert"][0]
    actual = col.get_note(saved.id)
    assert snapshot == updated.dict()
    assert {f["name"]: f["value"] for f in snapshot["fields"]} == dict(actual.items())
    assert snapshot["tags"] == actual.tags
    assert snapshot["mod"] == actual.mod
    assert snapshot["usn"] == actual.usn
    assert event["refresh"] == []


def test_delete_ids_mean_absent_including_already_missing(col, subscription, recorded_ops):
    saved = new_note()
    notes.delete_notes([saved.id, 123, saved.id])
    event = emit_last(recorded_ops, subscription)
    assert event["changes"]["notes"]["remove"] == [saved.id, 123]
    assert "cards" in event["refresh"]  # removed card IDs are not known here
    notes.delete_notes([saved.id])
    op = recorded_ops[-1]
    dispatch_op(op.result.changes, op.initiator)
    assert broker.drain(subscription) == []


@pytest.mark.parametrize("verb", [cards.suspend_cards, cards.unsuspend_cards,
                                  cards.bury_cards, cards.unbury_cards])
def test_scheduler_uses_targeted_fetch_without_rendering(col, subscription, recorded_ops,
                                                       monkeypatch, verb):
    saved = new_note()
    if verb is cards.unsuspend_cards:
        cards.suspend_cards(saved.cards)
    if verb is cards.unbury_cards:
        cards.bury_cards(saved.cards)
    monkeypatch.setattr(col, "get_card", lambda *a: pytest.fail("unexpected card load"))
    verb(saved.cards)
    event = emit_last(recorded_ops, subscription, ("cards",))
    assert event["changes"]["cards"]["fetch"] == saved.cards
    assert event["refresh"] == []


def test_compat_save_and_update_emit_ids(col, subscription, recorded_ops):
    spec = {"modelName": "Basic", "deckName": "Default",
            "fields": {"Front": "compat", "Back": "meaning"}}
    nid = notes.ac_add_note(spec)
    event = emit_last(recorded_ops, subscription, ("notes",))
    assert event["changes"]["notes"] == {"upsert": [], "fetch": [nid], "remove": []}
    notes.ac_update_note_fields(nid, {"Front": "updated"}, [])
    event = emit_last(recorded_ops, subscription, ("notes",))
    assert event["changes"]["notes"]["fetch"] == [nid]


def test_failed_write_has_no_event(col, subscription, recorded_ops):
    with pytest.raises(ResourceNotFoundError):
        notes.patch_note(123, {"fields": {"Front": "missing"}})
    assert recorded_ops[-1].initiator.changes == {}
    assert broker.drain(subscription) == []


def test_event_failure_does_not_fail_successful_operation(col, subscription, recorded_ops):
    def broken():
        raise RuntimeError("event serialization failed")

    assert ops.collection_op_call(lambda col: ops.ValueWithChanges(
        42, OpChanges(note=True), event_changes=broken)) == 42
    event = emit_last(recorded_ops, subscription, ("notes",))
    assert event["changes"] == {}
    assert event["refresh"] == ["notes"]


def test_no_listeners_skips_event_factory(col, recorded_ops):
    broker.start_session(col)
    try:
        assert ops.collection_op_call(lambda col: ops.ValueWithChanges(
            42, OpChanges(note=True),
            event_changes=lambda: pytest.fail("no subscriber needs this"))) == 42
    finally:
        broker.begin_drain()


def test_review_only_listener_skips_event_factory(col, recorded_ops):
    broker.start_session(col)
    broker.subscribe(types={"review"})
    try:
        assert ops.collection_op_call(lambda col: ops.ValueWithChanges(
            42, OpChanges(note=True),
            event_changes=lambda: pytest.fail("review listeners do not need records"))) == 42
    finally:
        broker.begin_drain()


def test_oversize_records_become_fetches_and_oversize_id_sets_invalidate():
    frozen = freeze_changes({"notes": {"upsert": [
        {"id": 7, "fields": ["x" * MAX_RESULT_BYTES]}]}})
    assert frozen == {"notes": {"upsert": [], "fetch": [7], "remove": []}}
    assert freeze_changes({"cards": {"fetch": list(range(MAX_RESULT_IDS + 1))}}) == {}


def test_projection_keeps_other_resources_and_input_hints_separate():
    event = {"type": "change", "refresh": ["notes", "cards", "models"],
             "changes": {"notes": {"upsert": [{"id": 1}]},
                         "cards": {"fetch": [2]}},
             "targets": {"notes": [999], "models": [3]}}
    scoped = _change_event(event, frozenset({"notes", "models"}))
    assert scoped["changes"] == {"notes": {"upsert": [{"id": 1}]}}
    assert scoped["refresh"] == ["models"]
    assert scoped["targets"]["notes"] == [999]  # never promoted to confirmed changes


def test_saved_editor_ids_support_fetch_after_debounce():
    event = {"type": "change", "refresh": ["notes", "cards"],
             "origin": "ui", "action": "notes.updated", "targets": {"notes": [10, 20]}}
    scoped = _change_event(event, frozenset({"notes", "cards"}))
    assert scoped["changes"]["notes"]["fetch"] == [10, 20]
    assert scoped["refresh"] == ["cards"]


@pytest.mark.parametrize("types", [None, "change", "change,refresh", "refresh"])
def test_http_delivers_records_or_explicit_invalidation_mode(client, col, subscription,
                                                          recorded_ops, monkeypatch, types):
    original = broker.subscribe
    saved = []

    def after_subscribe(**kwargs):
        token = original(**kwargs)
        saved.append(new_note())
        op = recorded_ops[-1]
        dispatch_op(op.result.changes, op.initiator)
        return token

    from test_v1_events import parse_frames

    from tsunagi.http.v1 import events as http_events

    monkeypatch.setattr(http_events, "broker", broker)
    monkeypatch.setattr(broker, "subscribe", after_subscribe)
    params = {"resources": "notes", "max_events": 1, "timeout": 1}
    if types is not None:
        params["types"] = types
    response = client.get("/v1/events", params=params)
    assert response.status_code == 200
    initial, update, close = parse_frames(response.text)
    assert initial[0] == "refresh"
    assert initial[1]["reason"] == "initial"
    assert close == ("close", {"reason": "max_events"})
    if types == "refresh":
        assert update[0] == "refresh"
        assert "changes" not in update[1]
    else:
        assert update[0] == "change"
        assert update[1]["changes"]["notes"]["upsert"] == [saved[0].dict()]
        assert set(update[1]["changes"]) == {"notes"}
        assert update[1]["refresh"] == []
    assert update[1]["seq"] > initial[1]["after_seq"]
