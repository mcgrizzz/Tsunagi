"""Completed mutation IDs, without event records or extra collection reads."""
import pytest
from anki.collection import OpChanges
from test_events_broker import recorded_ops as recorded_ops

from tsunagi.adapters import ops
from tsunagi.adapters.anki import cards, notes
from tsunagi.adapters.event_results import (
    MAX_RESULT_IDS,
    freeze_changes,
)
from tsunagi.adapters.events import broker, dispatch_op
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
    return {e["type"]: e for e in emitted if e["type"].split(".")[0] in resources}


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
    monkeypatch.setattr(notes.NoteInfo, "dict", unexpected)
    broker.subscribe(types={"change"})
    saved = new_note()
    assert reads == [saved.id]  # one authoritative save result, shared by subscribers
    event = emit_last(recorded_ops, subscription)
    assert event["notes.created"]["ids"] == [saved.id]
    assert event["cards.created"]["ids"] == saved.cards
    assert not any(name.endswith(".changed") for name in event)
    # Result objects may be changed by a caller after success. Queued events cannot.
    saved_id = saved.id
    saved.id = 123
    saved.cards.append(456)
    assert event["notes.created"]["ids"] == [saved_id]
    assert 456 not in event["cards.created"]["ids"]


def test_patch_returns_saved_fields_and_tags(col, subscription, recorded_ops):
    saved = new_note()
    col.db.execute("update notes set mod = 1 where id = ?", saved.id)
    updated = notes.patch_note(saved.id, {"fields": {"Front": "changed"},
                                          "tags": ["zebra", "Alpha", "Alpha"]})
    event = emit_last(recorded_ops, subscription, ("notes",))
    assert event["notes.updated"]["ids"] == [saved.id]
    snapshot = updated.dict()  # the ordinary write response still has the saved data
    actual = col.get_note(saved.id)
    assert snapshot == updated.dict()
    assert {f["name"]: f["value"] for f in snapshot["fields"]} == dict(actual.items())
    assert snapshot["tags"] == actual.tags
    assert snapshot["mod"] == actual.mod
    assert snapshot["usn"] == actual.usn
    assert not any(name.endswith(".changed") for name in event)


def test_delete_ids_mean_absent_including_already_missing(col, subscription, recorded_ops):
    saved = new_note()
    notes.delete_notes([saved.id, 123, saved.id])
    event = emit_last(recorded_ops, subscription)
    assert event["notes.deleted"]["ids"] == [saved.id, 123]
    assert event["cards.changed"]["ids"] is None  # removed card IDs are not known here
    notes.delete_notes([saved.id])
    op = recorded_ops[-1]
    dispatch_op(op.result.changes, op.initiator)
    assert broker.drain(subscription) == []


@pytest.mark.parametrize("verb", [cards.suspend_cards, cards.unsuspend_cards,
                                  cards.bury_cards, cards.unbury_cards])
def test_scheduler_reports_updated_ids_without_rendering(col, subscription, recorded_ops,
                                                       monkeypatch, verb):
    saved = new_note()
    if verb is cards.unsuspend_cards:
        cards.suspend_cards(saved.cards)
    if verb is cards.unbury_cards:
        cards.bury_cards(saved.cards)
    monkeypatch.setattr(col, "get_card", lambda *a: pytest.fail("unexpected card load"))
    verb(saved.cards)
    event = emit_last(recorded_ops, subscription, ("cards",))
    assert event["cards.updated"]["ids"] == saved.cards
    assert not any(name.endswith(".changed") for name in event)


def test_compat_save_and_update_emit_ids(col, subscription, recorded_ops):
    spec = {"modelName": "Basic", "deckName": "Default",
            "fields": {"Front": "compat", "Back": "meaning"}}
    nid = notes.ac_add_note(spec)
    event = emit_last(recorded_ops, subscription, ("notes",))
    assert event["notes.created"]["ids"] == [nid]
    notes.ac_update_note_fields(nid, {"Front": "updated"}, [])
    event = emit_last(recorded_ops, subscription, ("notes",))
    assert event["notes.updated"]["ids"] == [nid]


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
    assert set(event) == {"notes.changed"}
    assert event["notes.changed"]["ids"] is None


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


def test_id_lists_are_detached_and_bounded():
    ids = [7, 7, 8]
    frozen = freeze_changes({"notes": {"updated": ids}})
    ids.append(9)
    assert frozen == {"notes": {"updated": [7, 8]}}
    assert freeze_changes({"cards": {"updated": list(range(MAX_RESULT_IDS + 1))}}) == {}


def test_record_payloads_are_rejected():
    with pytest.raises(ValueError, match="only created/updated/deleted IDs"):
        freeze_changes({"notes": {"upsert": [{"id": 7, "fields": ["secret"]}]}})


def test_large_id_sets_do_not_leak_through_target_hints(subscription):
    from tsunagi.adapters.events import ApiOp

    ids = list(range(MAX_RESULT_IDS + 1))
    initiator = ApiOp({"note_ids": ids})
    initiator.changes = freeze_changes({"notes": {"updated": ids}})
    dispatch_op(OpChanges(note=True), initiator)
    event = next(e for e in broker.drain(subscription) if e["type"] == "notes.changed")
    assert event["ids"] is None
    assert "targets" not in event


def test_known_results_and_unknown_related_resources_are_distinct(subscription):
    broker.publish("change", affected=["notes", "cards", "models"],
                   changes={"notes": {"updated": [1]}, "cards": {"created": [2]}},
                   targets={"notes": [999], "models": [3]})
    events = {e["type"]: e for e in broker.drain(subscription)}
    assert set(events) == {"notes.updated", "cards.created", "models.changed"}
    assert events["notes.updated"]["ids"] == [1]
    assert events["models.changed"]["ids"] is None
    assert all("targets" not in e for e in events.values())
    assert len({e["seq"] for e in events.values()}) == 3


def test_add_dialog_reports_created_ids(subscription):
    from tsunagi.adapters.events import publish_note_added

    publish_note_added([10, 20])
    events = {e["type"]: e for e in broker.drain(subscription)}
    assert events["notes.created"]["ids"] == [10, 20]
    assert "notes.changed" not in events
    assert events["cards.changed"]["ids"] is None


@pytest.mark.parametrize("types", [None, "change", "notes.created", "notes.created,notes.changed"])
def test_http_delivers_named_events_with_only_ids(client, col, subscription,
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
    assert initial[0] == "ready"
    assert initial[1]["resources"] == ["notes"]
    assert close == ("close", {"reason": "max_events"})
    assert update[0] == update[1]["type"] == "notes.created"
    assert update[1]["ids"] == [saved[0].id]
    for obsolete in ("word", "upsert", "fields", "refresh", "fetch", "remove", "targets"):
        assert obsolete not in response.text
    assert update[1]["seq"] > initial[1]["after_seq"]
