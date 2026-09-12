"""Typing is omitted without losing API writes or other collection changes."""
from types import SimpleNamespace

import pytest
from anki.collection import OpChanges

from tsunagi.adapters import events
from tsunagi.http.v1 import events as http_events


@pytest.fixture
def stream(monkeypatch):
    broker = events.EventBroker()
    broker.start_session(object())
    monkeypatch.setattr(events, "broker", broker)
    token = broker.subscribe(types={"change"}, resources={"notes"})
    return broker, token


def test_typing_burst_is_discarded_without_filling_queue(stream):
    broker, token = stream
    for _ in range(events.MAX_QUEUED * 2):
        events.dispatch_op(OpChanges(note=True, note_text=True, browser_table=True), object())
    assert broker.drain(token) == []
    assert broker.ready(broker.subscribe())["after_seq"] == 0
    events.dispatch_op(OpChanges(card=True), object())
    assert [item["type"] for item in broker.drain(token)] == ["notes.changed"]


@pytest.mark.parametrize("handler", [None, events.ApiOp()])
def test_same_flags_from_undo_or_api_are_delivered(stream, handler):
    broker, token = stream
    events.dispatch_op(OpChanges(note=True, note_text=True), handler)
    assert len(broker.drain(token)) == 1


@pytest.mark.parametrize("extra", ["card", "tag", "notetype", "study_queues"])
def test_typing_filter_does_not_hide_other_operations(stream, extra):
    broker, token = stream
    changes = OpChanges(note=True, note_text=True, **{extra: True})
    events.dispatch_op(changes, object())
    assert len(broker.drain(token)) == 1


def test_unknown_future_changes_are_not_silenced():
    changes = SimpleNamespace(note=True, note_text=True, future_change=True,
                              DESCRIPTOR=SimpleNamespace(fields=[
                                  SimpleNamespace(name=name)
                                  for name in ("note", "note_text", "future_change")]))
    assert not events.is_ui_text_update(changes, object())


def test_real_note_edit_is_omitted_but_create_delete_and_undo_remain(col, stream):
    broker, token = stream
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "before"
    added = col.add_note(note, 1)
    events.dispatch_op(getattr(added, "changes", added), object())
    assert len(broker.drain(token)) == 1
    note["Front"] = "after"
    edited = col.update_note(note)
    events.dispatch_op(getattr(edited, "changes", edited), object())
    assert broker.drain(token) == []
    # An API edit with identical Anki flags must still be visible immediately.
    events.dispatch_op(getattr(edited, "changes", edited), events.ApiOp())
    assert len(broker.drain(token)) == 1
    removed = col.remove_notes([note.id])
    events.dispatch_op(getattr(removed, "changes", removed), object())
    assert len(broker.drain(token)) == 1
    undone = col.undo()
    events.dispatch_op(getattr(undone, "changes", undone), None)
    assert len(broker.drain(token)) == 1


def test_http_typing_does_not_consume_event_limit(client, stream, monkeypatch):
    from test_v1_events import parse_frames

    broker, _ = stream
    original = broker.subscribe

    def subscribe(**kwargs):
        token = original(**kwargs)
        events.dispatch_op(OpChanges(note=True, note_text=True), object())
        events.publish_note_added([42])
        return token

    monkeypatch.setattr(broker, "subscribe", subscribe)
    monkeypatch.setattr(http_events, "broker", broker)
    response = client.get("/v1/events?resources=notes&max_events=1&timeout=1")
    initial, change, close = parse_frames(response.text)
    assert initial[0] == "ready"
    assert change[0] == "notes.created"
    assert change[1]["ids"] == [42]
    assert close == ("close", {"reason": "max_events"})
