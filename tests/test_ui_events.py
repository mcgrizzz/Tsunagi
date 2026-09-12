"""Add-dialog completion stays observable; editor updates are left untouched."""
from types import SimpleNamespace

import pytest
from anki.collection import OpChanges
from anki.notes_pb2 import AddNoteResponse

from tsunagi.adapters.events import (
    ApiOp,
    affected_resources,
    broker,
    dispatch_op,
    publish_note_added,
)
from tsunagi.adapters.ui_events import UiEventObservers


@pytest.fixture
def stream():
    broker.reset()
    token = broker.subscribe(resources={"notes"})
    yield token
    broker.reset()


@pytest.fixture
def observer():
    state = SimpleNamespace(col=object())
    observer = UiEventObservers(lambda: state.col)
    yield observer, state
    observer.uninstall()


def add_result():
    result = AddNoteResponse(note_id=42)
    getattr(result.changes, "changes", result.changes).note = True
    return result.SerializeToString()


def test_modern_add_dialog_uses_confirmed_response(observer, stream):
    watcher, _ = observer
    output = add_result()
    handlers = {"addNote": lambda: output}
    callbacks = []
    watcher.watch_add_note_handler(handlers, callbacks.append)
    assert handlers["addNote"]() is output
    assert broker.drain(stream) == []
    callbacks.pop()()
    event = broker.drain(stream)[0]
    assert event["ids"] == [42]
    assert event["type"] == "notes.created"


def test_editor_update_handler_is_not_wrapped(observer, stream):
    watcher, _ = observer
    update = lambda: OpChanges(note=True, note_text=True).SerializeToString()
    handlers = {"addNote": add_result, "updateNotes": update}
    callbacks = []
    watcher.watch_add_note_handler(handlers, callbacks.append)
    assert handlers["updateNotes"] is update
    assert handlers["updateNotes"]() == update()
    assert callbacks == []
    assert broker.drain(stream) == []


def test_add_failure_and_noop_do_not_emit(observer, stream):
    watcher, _ = observer
    callbacks = []

    def fail():
        raise ValueError("save failed")

    handlers = {"addNote": fail}
    watcher.watch_add_note_handler(handlers, callbacks.append)
    with pytest.raises(ValueError, match="save failed"):
        handlers["addNote"]()
    assert callbacks == []
    handlers = {"addNote": AddNoteResponse(note_id=42).SerializeToString}
    watcher.watch_add_note_handler(handlers, callbacks.append)
    handlers["addNote"]()
    for callback in callbacks:
        callback()
    assert broker.drain(stream) == []


@pytest.mark.parametrize("disable", [False, True])
def test_profile_switch_or_uninstall_drops_queued_notification(observer, stream, disable):
    watcher, state = observer
    handlers = {"addNote": add_result}
    callbacks = []
    watcher.watch_add_note_handler(handlers, callbacks.append)
    handlers["addNote"]()
    if disable:
        watcher.uninstall()
        assert handlers["addNote"] is add_result
    else:
        state.col = object()
    callbacks.pop()()
    assert broker.drain(stream) == []


def test_uninstall_preserves_another_addons_wrapper(observer, stream):
    watcher, _ = observer
    callbacks = []
    handlers = {"addNote": add_result}
    watcher.watch_add_note_handler(handlers, callbacks.append)
    ours = handlers["addNote"]
    other = lambda: ours()
    handlers["addNote"] = other
    watcher.uninstall()
    assert handlers["addNote"] is other
    assert other() == add_result()
    assert callbacks == []


def test_no_listeners_does_not_parse_response(observer):
    broker.reset()
    watcher, _ = observer
    callbacks = []
    handlers = {"addNote": lambda: b"untouched"}
    watcher.watch_add_note_handler(handlers, callbacks.append)
    assert handlers["addNote"]() == b"untouched"
    assert callbacks == []


def test_unrecognized_payload_preserves_original_result(observer, stream):
    watcher, _ = observer
    callbacks = []
    handlers = {"addNote": lambda: b"bad protobuf"}
    watcher.watch_add_note_handler(handlers, callbacks.append)
    assert handlers["addNote"]() == b"bad protobuf"
    assert callbacks == []
    assert broker.drain(stream) == []


def test_collection_lookup_failure_does_not_prevent_add(stream):
    def unavailable():
        raise RuntimeError("closed profile")

    watcher = UiEventObservers(unavailable)
    handlers = {"addNote": add_result}
    watcher.watch_add_note_handler(handlers, lambda callback: callback())
    try:
        assert handlers["addNote"]() == add_result()
        assert broker.drain(stream) == []
    finally:
        watcher.uninstall()


def test_added_note_not_draft_and_no_extra_queries(stream):
    publish_note_added([0])
    assert broker.drain(stream) == []
    publish_note_added([42])
    event = broker.drain(stream)[0]
    assert event["type"] == "notes.created"
    assert event["ids"] == [42]


def test_api_targets_are_hints_and_unknown_flags_request_full_refresh(stream):
    dispatch_op(OpChanges(card=True), ApiOp({"card_ids": [42, 42, 99]}))
    event = broker.drain(stream)[0]
    assert event["type"] == "notes.changed"
    assert event["ids"] is None
    assert "targets" not in event
    assert affected_resources(["note", "future_flag"]) == ["collection"]
    assert affected_resources(["browser_table"]) == ["collection"]


def test_refresh_covers_search_membership_without_review_row_changes():
    for flag in ("note", "note_text", "tag", "deck", "notetype"):
        assert {"notes", "cards", "reviews"} <= set(affected_resources([flag]))
