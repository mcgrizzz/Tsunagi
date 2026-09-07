"""Fixed upstream differences, also checked without an upstream checkout."""

from pathlib import Path

import pytest

from tsunagi.http.compat.registry import registry


def rpc(client, action, **params):
    assert registry.is_registered(action)
    response = client.post("/", json={"action": action, "version": 6, "params": params})
    assert response.status_code == 200
    return response.json()


def test_missing_note_modification_times(client):
    assert rpc(client, "notesModTime", notes=[0, 9999999999999]) == {
        "result": [{}, {}], "error": None,
    }


def test_zero_card_keeps_other_results(client, col):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "zero card regression"
    col.add_note(note, 1)
    card_id = col.find_cards("")[0]
    response = rpc(client, "cardsInfo", cards=[0, card_id, 0, card_id])
    assert response["error"] is None
    assert response["result"][0] == response["result"][2] == {}
    assert response["result"][1] == response["result"][3]
    assert response["result"][1]["cardId"] == card_id


@pytest.mark.parametrize("action", ["findCards", "findNotes"])
@pytest.mark.parametrize("query", ["(", 123])
def test_search_preserves_backend_errors(client, col, action, query):
    search = col.find_cards if action == "findCards" else col.find_notes
    with pytest.raises(Exception) as error:
        search(query)
    assert rpc(client, action, query=query) == {"result": None, "error": str(error.value)}


def test_argument_error_strings(client):
    assert rpc(client, "version", unexpected=True) == {
        "result": None,
        "error": "AnkiConnect.version() got an unexpected keyword argument 'unexpected'",
    }
    assert rpc(client, "cardsInfo", cards=None) == {
        "result": None, "error": "'NoneType' object is not iterable",
    }


def test_deck_statistics_and_missing_card_fallback(client, col):
    deck = col.decks.id("Parent::Child")
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "deck statistics regression"
    col.add_note(note, deck)
    response = rpc(client, "getDeckStats", decks=["Default", "Parent::Child"])
    assert response["error"] is None
    assert set(response["result"]) == {str(deck)}
    assert response["result"][str(deck)]["name"] == "Child"
    assert rpc(client, "getDecks", cards=[9999999999999, 0, 9999999999999]) == {
        "result": {col.decks.get(None)["name"]: [9999999999999, 0, 9999999999999]},
        "error": None,
    }


@pytest.mark.parametrize("count,repetitions", [(999, 1), (1000, 2)])
def test_note_card_repetition_matches_upstream_batches(client, col, count, repetitions):
    note = col.new_note(col.models.by_name("Basic (and reversed card)"))
    note["Front"], note["Back"] = "front", "back"
    col.add_note(note, 1)
    cards = sorted(col.find_cards(""), key=lambda cid: col.get_card(cid).ord)
    assert len(cards) == 2
    response = rpc(client, "notesInfo", notes=[note.id] * count)
    assert response["error"] is None
    assert len(response["result"]) == count
    assert all(info["cards"] == cards * repetitions for info in response["result"])


def test_null_delete_existing_keeps_original_media(client, col):
    col.media.write_data("collision.txt", b"original")
    response = rpc(client, "storeMediaFile", filename="collision.txt", data="bmV3", deleteExisting=None)
    assert response["error"] is None
    assert response["result"] != "collision.txt"
    assert (Path(col.media.dir()) / "collision.txt").read_bytes() == b"original"
    assert (Path(col.media.dir()) / response["result"]).read_bytes() == b"new"


@pytest.mark.parametrize("front,expected", [("new probe", True), ("existing", False)])
def test_note_probe_writes_media_without_inserting_note(client, col, front, expected):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "existing"
    col.add_note(note, 1)
    response = rpc(client, "canAddNote", note={
        "deckName": "Default", "modelName": "Basic", "fields": {"Front": front},
        "audio": {"filename": "probe.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
    })
    assert response == {"result": expected, "error": None}
    assert list(col.find_notes("")) == [note.id]
    assert col.get_note(note.id)["Back"] == ""
    assert (Path(col.media.dir()) / "probe.mp3").read_bytes() == b"audio"
