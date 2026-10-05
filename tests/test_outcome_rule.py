"""How an outcome is reported (backlog 6.116): a mistake is an HTTP error, `ok: false`
only means Anki can't do it right now. The AnkiConnect Shim keeps AnkiConnect's answers."""
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture()
def add_dialog(monkeypatch, col):
    import aqt

    editor = SimpleNamespace(note=col.new_note(col.models.by_name("Basic")), loadNote=lambda: None)
    dialog = SimpleNamespace(editor=editor, set_deck=lambda did: None, set_note_type=lambda mid: None)
    registry = {"AddCards": (None, dialog)}
    monkeypatch.setattr(aqt, "dialogs", SimpleNamespace(_dialogs=registry, open=lambda name, parent: dialog),
                        raising=False)
    return registry


@pytest.mark.parametrize("path", ["/v1/gui:add-cards", "/v1/gui:set-add-note-data"])
@pytest.mark.parametrize("body", [{"deck_name": "Nope"}, {"note_type_name": "Nope"}])
def test_add_cards_names_a_missing_deck_or_note_type_with_404(client, add_dialog, path, body):
    response = client.post(path, json={"deck_name": "Default", "note_type_name": "Basic", **body,
                                       "fields": {"Front": "x"}})
    assert response.status_code == 404
    assert response.json()["detail"] == ("Deck Nope not found" if "deck_name" in body else "Note type Nope not found")


def test_the_shim_keeps_ankiconnects_error_for_a_missing_deck(client, add_dialog):
    answer = client.post("/", json={"action": "guiAddCards", "version": 6, "params": {"note": {
        "deckName": "Nope", "modelName": "Basic", "fields": {"Front": "x"}}}}).json()
    assert answer == {"result": None, "error": "deck was not found: Nope"}


def test_set_add_note_data_is_ok_false_when_add_cards_is_closed(client, add_dialog):
    add_dialog.clear()
    answer = client.post("/v1/gui:set-add-note-data", json={"fields": {"Front": "x"}})
    assert answer.status_code == 200
    assert {k: v for k, v in answer.json().items() if k != "stats"} == {"ok": False}


@pytest.mark.parametrize("path", ["/v1/gui:deck-overview", "/v1/gui:deck-review"])
def test_a_missing_deck_is_404(client, path):
    assert client.post(path, json={"deck_name": "Nope"}).status_code == 404
    assert client.post(path, json={"deck_id": 999}).status_code == 404


def test_selecting_a_missing_card_is_404(client):
    assert client.post("/v1/gui:select-card", json={"card_id": 123}).status_code == 404


def test_loading_a_missing_profile_is_404(client, monkeypatch):
    from aqt import mw

    monkeypatch.setitem(sys.modules, "aqt.qt", SimpleNamespace(QTimer=None))
    monkeypatch.setattr(mw.pm, "profiles", lambda: ["User 1"], raising=False)
    assert client.post("/v1/profiles:load", json={"name": "Nope"}).status_code == 404


def test_reviews_for_missing_cards_are_404_and_nothing_is_inserted(client, col):
    client.post("/v1/notes", json={"note_type_name": "Basic", "deck_name": "Default", "fields": {"Front": "a"}})
    card = col.find_cards("")[0]
    response = client.post("/v1/reviews", json={"reviews": [
        {"id": 1700000000000, "card_id": card}, {"id": 1700000000001, "card_id": 99}]})
    assert response.status_code == 404 and "99" in response.json()["detail"]
    assert client.get("/v1/reviews").json()["items"] == []


def test_a_note_file_by_path_without_local_files_is_403(client, col, tmp_path):
    source = tmp_path / "a.mp3"
    source.write_bytes(b"x")
    response = client.post("/v1/notes", json={"note_type_name": "Basic", "deck_name": "Default",
                                              "fields": {"Front": "a"}, "audio": {"path": str(source), "fields": []}})
    assert response.status_code == 403 and col.note_count() == 0


@pytest.fixture()
def undo_hook(monkeypatch):
    import aqt

    heard = []
    monkeypatch.setattr(aqt, "gui_hooks", SimpleNamespace(state_did_undo=heard.append), raising=False)
    return heard


def test_undo_with_nothing_to_undo_is_null(client, undo_hook):
    answer = client.post("/v1/gui:undo").json()
    assert answer["undone"] is None and undo_hook == []


def test_undo_names_the_step_it_undid(client, col, undo_hook):
    client.post("/v1/notes", json={"note_type_name": "Basic", "deck_name": "Default", "fields": {"Front": "a"}})
    answer = client.post("/v1/gui:undo").json()
    assert answer["undone"] and col.note_count() == 0
    assert [out.operation for out in undo_hook] == [answer["undone"]]


# Add Cards prefilled as create takes a note (6.111): exact fields, and files stored and referenced.

def b64(data):
    import base64
    return base64.b64encode(data).decode()


def test_add_cards_stores_files_and_references_them(client, col, add_dialog):
    import aqt

    shown = []
    dialog = add_dialog["AddCards"][1]
    dialog.editor.set_note = shown.append
    dialog.activateWindow = dialog.setAndFocusNote = lambda *a: None
    dialog.closeWithCallback = lambda then: then()   # the open dialog closes, then refills
    aqt.dialogs.open = lambda name, parent: dialog
    response = client.post("/v1/gui:add-cards", json={
        "deck_name": "Default", "note_type_name": "Basic", "fields": {"Front": "犬"},
        "audio": {"data": b64(b"bark"), "filename": "inu.mp3", "fields": ["Back"]}})
    assert response.status_code == 200, response.text
    assert [f["filename"] for f in response.json()["files"]] == ["inu.mp3"] and col.media.have("inu.mp3")
    assert [(n["Front"], n["Back"]) for n in shown] == [("犬", "[sound:inu.mp3]")]


def test_add_cards_refuses_a_field_the_note_type_lacks(client, col, add_dialog):
    response = client.post("/v1/gui:add-cards", json={
        "deck_name": "Default", "note_type_name": "Basic", "fields": {"Fornt": "x"}})
    assert response.status_code == 400 and "Fornt" in response.text   # it was dropped silently


def test_add_cards_with_a_file_by_path_needs_local_files(client, col, add_dialog, tmp_path):
    source = tmp_path / "a.mp3"
    source.write_bytes(b"x")
    response = client.post("/v1/gui:add-cards", json={
        "deck_name": "Default", "note_type_name": "Basic", "fields": {"Front": "a"},
        "audio": {"path": str(source), "fields": ["Back"]}})
    assert response.status_code == 403 and not col.media.have("a.mp3")
