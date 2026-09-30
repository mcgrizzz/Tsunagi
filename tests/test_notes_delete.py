"""POST /v1/notes:delete: several notes in one request and one undo step (backlog 6.60)."""
import pytest


@pytest.fixture()
def ids(client, col):
    out = []
    for front in ("犬", "猫", "鳥"):
        r = client.post("/v1/notes", json={"modelName": "Basic", "deckName": "Default",
                                           "fields": {"Front": front, "Back": ""}})
        out.append(r.json()["created"][0]["id"])
    return out


def test_deletes_notes_and_their_cards_as_one_undo_step(client, col, ids):
    cards = [c for n in ids[:2] for c in col.card_ids_of_note(n)]
    r = client.post("/v1/notes:delete", json={"note_ids": ids[:2]})
    assert r.status_code == 200, r.text
    assert r.json()["affected"] == 2
    assert set(col.find_notes("")) == {ids[2]}
    assert not set(cards) & set(col.find_cards(""))
    assert col.undo_status().undo == "Delete Note"
    col.undo()
    assert set(col.find_notes("")) == set(ids)


def test_missing_and_repeated_ids_count_once_and_camel_case_works(client, col, ids):
    r = client.post("/v1/notes:delete", json={"noteIds": [ids[0], 999999, ids[0]]})
    assert r.json()["affected"] == 1
    assert set(col.find_notes("")) == set(ids[1:])


def test_no_ids_writes_nothing(client, col, ids):
    before = col.undo_status()
    r = client.post("/v1/notes:delete", json={"note_ids": []})
    assert r.json()["affected"] == 0
    assert col.undo_status() == before


def test_body_without_ids_is_a_422(client, col):
    assert client.post("/v1/notes:delete", json={}).status_code == 422
