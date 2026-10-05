"""A deck or note type is named by its name or its id in every request (backlog 6.110)."""
import pytest


def test_export_takes_a_deck_id(client, col, tmp_path):
    path = tmp_path / "by-id.apkg"
    assert client.post("/v1/collection:export", json={"deck_id": 1, "path": str(path)}).status_code == 200
    assert path.is_file()
    assert client.post("/v1/collection:export", json={"deck_id": 999, "path": str(path)}).status_code == 404
    assert client.post("/v1/collection:export", json={"path": str(path)}).status_code == 422


def test_find_replace_takes_a_note_type_id(client, col):
    basic = col.models.by_name("Basic")
    answer = client.post("/v1/note-types:find-replace", json={
        "find": "{{Front}}", "replace": "{{Front}} ", "note_type_id": basic["id"], "back": False, "css": False})
    assert answer.json()["affected"] == 1
    assert col.models.get(basic["id"])["tmpls"][0]["qfmt"].startswith("{{Front}} ")
    assert client.post("/v1/note-types:find-replace", json={
        "find": "x", "replace": "y", "note_type_id": 999}).status_code == 404


@pytest.fixture()
def opened(monkeypatch):
    """The names the GUI adapter is called with, without a window."""
    from tsunagi.adapters.anki import gui

    calls = []
    monkeypatch.setattr(gui, "deck_review", lambda name: calls.append(name) or True)
    monkeypatch.setattr(gui, "add_cards", lambda spec, **files: calls.append(spec) or 0)
    monkeypatch.setattr(gui, "set_add_note_data", lambda spec, append: calls.append(spec) or True)
    return calls


def test_deck_verbs_take_a_deck_id(client, col, opened):
    assert client.post("/v1/gui:deck-review", json={"deck_id": 1}).status_code == 200
    assert client.post("/v1/gui:deck-review", json={"deck_id": 1, "deck_name": "Other"}).status_code == 200
    assert opened == ["Default", "Default"]  # the id wins when both are sent
    assert client.post("/v1/gui:deck-review", json={}).status_code == 422


def test_add_cards_takes_ids(client, col, opened):
    basic = col.models.by_name("Basic")
    assert client.post("/v1/gui:add-cards", json={
        "deck_id": 1, "note_type_id": basic["id"], "fields": {"Front": "x"}}).status_code == 200
    assert client.post("/v1/gui:set-add-note-data", json={"note_type_id": basic["id"]}).status_code == 200
    assert opened == [{"deckName": "Default", "modelName": "Basic", "fields": {"Front": "x"}, "tags": None},
                      {"modelName": "Basic"}]
    assert client.post("/v1/gui:add-cards", json={"deck_id": 999, "note_type_name": "Basic"}).status_code == 404


def test_add_cards_prefills_only_with_a_deck_and_a_note_type(client, opened):
    # It answered "Deck None not found" for a note type without a deck.
    response = client.post("/v1/gui:add-cards", json={"note_type_name": "Basic", "fields": {"Front": "x"}})
    assert response.status_code == 422 and "deck and its note type" in response.text
    assert client.post("/v1/gui:add-cards").status_code == 200   # an empty dialog
    assert opened == [None]


def test_check_takes_one_note_or_an_array(client):
    note = {"note_type_name": "Basic", "deck_name": "Default", "fields": {"Front": "a"}}
    one = client.post("/v1/notes:check", json=note).json()["results"]
    many = client.post("/v1/notes:check", json=[note, note]).json()["results"]
    assert [r["index"] for r in one] == [0] and [r["index"] for r in many] == [0, 1]
    assert client.post("/v1/notes:check", json={"notes": [note]}).status_code == 422


def test_upsert_no_longer_lists_files(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["NoteUpsert"]
    assert not {"audio", "video", "picture"} & set(schema["properties"])

