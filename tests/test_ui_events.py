"""Save-boundary regression checks: IDs must belong to completed operations."""
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from anki.collection import OpChanges
from anki.notes_pb2 import AddNoteResponse, UpdateNotesRequest

from tsunagi.adapters.events import (
    ApiOp,
    broker,
    dispatch_op,
    publish_note_change,
    refresh_resources,
)
from tsunagi.adapters.ui_events import UiEventObservers


@pytest.fixture
def stream():
    broker.reset()
    token = broker.subscribe()
    yield token
    broker.reset()


@pytest.fixture
def observer():
    state = SimpleNamespace(col=object())
    observer = UiEventObservers(lambda: state.col)
    yield observer, state
    observer.uninstall()


class DeferredOperation:
    """Controllable completion boundary; the observer must leave it intact."""
    def __init__(self):
        self.pending = []

    def _run(self, mw, work, on_done):
        self.pending.append((work, on_done))
        return "scheduled"


def editor_save(observer, state, note_id):
    operation = DeferredOperation()
    note = SimpleNamespace(id=note_id)
    namespace = {"update_note": lambda **kw: operation}
    observer.watch_editor_factory(namespace)
    assert namespace["update_note"](parent=None, note=note) is operation
    return operation, note, namespace


def future(result=None, error=None):
    f = Future()
    if error:
        f.set_exception(error)
    else:
        f.set_result(result)
    return f


def test_saved_id_survives_editor_switch_and_only_enriches_its_operation(observer, stream):
    watcher, state = observer
    operation, note, _ = editor_save(watcher, state, 42)
    changes = OpChanges(note=True)

    def completed(f):
        # A callback can run unrelated work before Anki emits the save's event.
        dispatch_op(OpChanges(card=True), object())
        dispatch_op(f.result(), object())
        return "callback result"

    assert operation._run(state, lambda: changes, completed) == "scheduled"
    note.id = 99
    assert broker.drain(stream) == []
    _, done = operation.pending[0]
    assert done(future(changes)) == "callback result"
    unrelated, saved = broker.drain(stream)
    assert unrelated["targets"] == {}
    assert saved["targets"] == {"notes": [42]}
    assert saved["action"] == "notes.updated"
    assert saved["origin"] == "ui"
    assert set(saved["refresh"]) >= {"notes", "cards", "models"}
    dispatch_op(changes, object())
    assert broker.drain(stream)[0]["targets"] == {}  # context was cleared


@pytest.mark.parametrize("error,no_change", [(True, False), (False, True)])
def test_failed_or_unchanged_save_keeps_callback_and_emits_nothing(observer, stream,
                                                                error, no_change):
    watcher, state = observer
    operation, _, _ = editor_save(watcher, state, 42)
    seen = []

    def completed(f):
        seen.append(f)
        if f.exception() is None:
            dispatch_op(f.result(), object())

    operation._run(state, lambda: None, completed)
    f = future(OpChanges(), ValueError("failed") if error else None)
    operation.pending[0][1](f)
    assert seen == [f]
    assert broker.drain(stream) == []


@pytest.mark.parametrize("disable", [False, True])
def test_profile_switch_or_uninstall_drops_identity_not_completion(observer, stream, disable):
    watcher, state = observer
    operation, _, namespace = editor_save(watcher, state, 42)
    operation._run(state, lambda: None, lambda f: dispatch_op(f.result(), object()))
    if disable:
        watcher.uninstall()
        assert namespace["update_note"](note=None) is operation
    else:
        state.col = object()
    operation.pending[0][1](future(OpChanges(note=True)))
    event = broker.drain(stream)[0]
    assert event["targets"] == {}
    assert event["action"] == "collection.changed"


def test_success_callback_exception_does_not_leak_context(observer, stream):
    watcher, state = observer
    operation, _, _ = editor_save(watcher, state, 42)
    changes = OpChanges(note=True)

    def completed(f):
        try:
            raise RuntimeError("another callback failed")
        finally:
            dispatch_op(f.result(), object())

    operation._run(state, lambda: None, completed)
    with pytest.raises(RuntimeError, match="another callback"):
        operation.pending[0][1](future(changes))
    assert broker.drain(stream)[0]["targets"] == {"notes": [42]}
    dispatch_op(changes, object())
    assert broker.drain(stream)[0]["targets"] == {}


def test_no_listener_leaves_operation_uninstrumented(observer):
    broker.reset()
    watcher, state = observer
    operation, _, _ = editor_save(watcher, state, 42)
    assert "_run" not in vars(operation)


def test_uninstall_preserves_another_addons_wrapper(observer):
    watcher, _ = observer
    original = lambda **kw: DeferredOperation()
    namespace = {"update_note": original}
    watcher.watch_editor_factory(namespace)
    ours = namespace["update_note"]
    other = lambda **kw: ours(**kw)
    namespace["update_note"] = other
    watcher.uninstall()
    assert namespace["update_note"] is other
    assert "_run" not in vars(other(note=SimpleNamespace(id=42)))


@pytest.mark.parametrize("name", ["addNote", "updateNotes"])
def test_modern_editor_uses_confirmed_response_and_request_ids(observer, stream, name):
    watcher, _ = observer
    request = UpdateNotesRequest()
    request.notes.add(id=42)
    result = AddNoteResponse(note_id=42)
    getattr(result.changes, "changes", result.changes).note = True
    output = result.SerializeToString() if name == "addNote" else OpChanges(note=True).SerializeToString()
    handlers = {name: lambda: output}
    callbacks = []
    watcher.watch_backend_handlers(handlers, request.SerializeToString, callbacks.append)
    assert handlers[name]() is output
    request.notes[0].id = 99
    assert broker.drain(stream) == []
    callbacks.pop()()
    event = broker.drain(stream)[0]
    assert event["targets"] == {"notes": [42]}
    assert event["action"] == ("notes.created" if name == "addNote" else "notes.updated")


def test_modern_editor_failure_and_noop_do_not_emit(observer, stream):
    watcher, _ = observer
    request = UpdateNotesRequest()
    request.notes.add(id=42)
    callbacks = []

    def fail():
        raise ValueError("save failed")

    handlers = {"addNote": fail, "updateNotes": lambda: OpChanges().SerializeToString()}
    watcher.watch_backend_handlers(handlers, request.SerializeToString, callbacks.append)
    with pytest.raises(ValueError, match="save failed"):
        handlers["addNote"]()
    handlers["updateNotes"]()
    for callback in callbacks:
        callback()
    assert broker.drain(stream) == []


def test_modern_editor_profile_switch_drops_queued_notification(observer, stream):
    watcher, state = observer
    result = AddNoteResponse(note_id=42)
    getattr(result.changes, "changes", result.changes).note = True
    handlers = {"addNote": result.SerializeToString}
    callbacks = []
    watcher.watch_backend_handlers(handlers, lambda: b"", callbacks.append)
    handlers["addNote"]()
    state.col = object()
    callbacks.pop()()
    assert broker.drain(stream) == []


def test_unrecognized_backend_payload_preserves_original_result(observer, stream):
    watcher, _ = observer
    callbacks = []
    handlers = {"addNote": lambda: b"bad protobuf", "updateNotes": lambda: b"untouched"}
    watcher.watch_backend_handlers(handlers, lambda: b"bad protobuf", callbacks.append)
    assert handlers["addNote"]() == b"bad protobuf"
    assert handlers["updateNotes"]() == b"untouched"
    assert callbacks == []
    assert broker.drain(stream) == []


def test_added_note_not_draft_and_no_extra_queries(stream):
    publish_note_change([0], "notes.created")
    assert broker.drain(stream) == []
    publish_note_change([42], "notes.created")
    event = broker.drain(stream)[0]
    assert event["action"] == "notes.created"
    assert event["targets"] == {"notes": [42]}


def test_api_targets_are_hints_and_unknown_flags_request_full_refresh(stream):
    dispatch_op(OpChanges(card=True), ApiOp({"card_ids": [42, 42, 99]}))
    event = broker.drain(stream)[0]
    assert event["targets"] == {"cards": [42, 99]}
    assert event["refresh"] == ["cards", "decks", "notes", "reviews", "scheduler"]
    assert refresh_resources(["note", "future_flag"]) == ["collection"]
    assert refresh_resources(["browser_table"]) == ["collection"]


def test_refresh_covers_search_membership_without_review_row_changes():
    # A saved note's tag/field edit or a deck rename changes which historical
    # reviews match an Anki search even when no revlog entry was written.
    for flag in ("note", "note_text", "tag", "deck", "notetype"):
        assert {"notes", "cards", "reviews"} <= set(refresh_resources([flag]))
