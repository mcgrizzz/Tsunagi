"""Protect experimental drafts until their update interface is supported."""

import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tsunagi.adapters.anki import gui
from tsunagi.app import app


@pytest.fixture
def windows(monkeypatch):
    dialogs = {}
    monkeypatch.setattr(gui, "_existing_dialog", dialogs.get)
    monkeypatch.setattr(gui, "call_on_main", lambda fn, *args: fn(*args))
    monkeypatch.setitem(sys.modules, "aqt", SimpleNamespace(mw=SimpleNamespace(col=object())))
    return dialogs


@pytest.mark.parametrize("legacy_open", [False, True])
@pytest.mark.parametrize("operation", ["open", "prefill", "detect", "update"])
def test_experimental_window_rejects_before_open_or_media(monkeypatch, windows, legacy_open, operation):
    draft = SimpleNamespace(fields={"Front": "unsaved work"})
    windows["NewAddCards"] = SimpleNamespace(editor=draft)
    if legacy_open:
        windows["AddCards"] = SimpleNamespace(editor=SimpleNamespace(note=draft))

    def unexpected(*args, **kwargs):
        pytest.fail("An unsupported window must be rejected before opening or loading media")

    monkeypatch.setattr(gui, "_open_dialog", unexpected)
    note = {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "replacement"}}
    with pytest.raises(gui.ValidationError, match="experimental Add window is open"):
        if operation == "open":
            gui.add_cards()
        elif operation == "prefill":
            gui.add_cards(note, _load_media=unexpected)
        elif operation == "detect":
            gui.add_note_dialog_open()
        else:
            gui.set_add_note_data(note, _load_media=unexpected)
    assert draft.fields == {"Front": "unsaved work"}


def test_legacy_window_detection_and_closed_response_are_preserved(windows):
    assert gui.add_note_dialog_open() is False
    assert gui.set_add_note_data({"fields": {}}) == gui.ADD_DIALOG_CLOSED
    windows["AddCards"] = SimpleNamespace(editor=object())
    assert gui.add_note_dialog_open() is True


@pytest.mark.parametrize("action", ["guiAddCards", "guiAddNoteSetData"])
def test_compatibility_response_explains_the_unsupported_editor(windows, action):
    windows["NewAddCards"] = SimpleNamespace(editor=object())
    params = {"note": {"fields": {}}} if action == "guiAddNoteSetData" else {}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post("/", json={"action": action, "version": 6, "params": params})
    assert response.status_code == 200
    assert response.json()["result"] is None
    assert "experimental Add window is open" in response.json()["error"]


def test_delayed_refill_does_not_open_a_window_after_experimental_editor_appears(
    monkeypatch, windows, caplog,
):
    import anki.notes
    import aqt

    from tsunagi.adapters.anki import notes

    pending = []
    windows["AddCards"] = SimpleNamespace(closeWithCallback=pending.append)
    aqt.mw.col = SimpleNamespace(
        decks=SimpleNamespace(by_name=lambda name: {"id": 1}, select=lambda did: None),
        models=SimpleNamespace(
            by_name=lambda name: {"id": 2},
            set_current=lambda model: None,
            update=lambda model: None,
        ),
    )
    monkeypatch.setattr(anki.notes, "Note", lambda *args: SimpleNamespace(id=0))
    monkeypatch.setattr(notes, "_ac_apply_fields", lambda *args: None)
    monkeypatch.setattr(gui, "_open_dialog", lambda name: pytest.fail("must not open a second window"))

    assert gui.add_cards({"deckName": "Default", "modelName": "Basic"}) == 0
    assert len(pending) == 1
    windows["NewAddCards"] = SimpleNamespace(editor=object())
    pending[0]()
    assert "experimental Add window is open" in caplog.text
