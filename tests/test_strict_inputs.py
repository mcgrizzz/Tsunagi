"""
Inputs that were accepted and then quietly did something else (backlog 6.75):
a card column Anki doesn't save, a bad step in a batch, a tag with a space.
"""
import pytest


@pytest.fixture()
def note(client):
    return client.post("/v1/notes", json={"model_name": "Basic", "deck_name": "Default",
                                          "fields": {"Front": "a", "Back": ""}}).json()["created"][0]["id"]


@pytest.fixture()
def cid(col, note):
    return col.card_ids_of_note(note)[0]


@pytest.mark.parametrize("values,force", [
    ({"nope": 1}, False),        # not a column: answered 200 and wrote nothing
    ({"mod": 5}, True),          # columns Anki sets itself: silently ignored
    ({"usn": 5}, True),
    ({"data": "{}"}, False),
    ({"id": 0}, True),           # identifies the card: the write went to card 0
])
def test_set_values_takes_only_the_columns_anki_saves(client, col, cid, values, force):
    before = col.get_card(cid).due
    resp = client.post("/v1/cards:set-values", json={"card_id": cid, "values": values, "force": force})
    assert resp.status_code == 400, resp.text
    name = next(iter(values))
    assert f"can't write {name}" in resp.json()["detail"] and "due" in resp.json()["detail"]
    assert col.get_card(cid).due == before


@pytest.mark.parametrize("value", [None, True, "5", 1.5])
def test_set_values_takes_integers(client, cid, value):
    resp = client.post("/v1/cards:set-values", json={"card_id": cid, "values": {"due": value}})
    assert resp.status_code == 400 and "due must be an integer" in resp.json()["detail"]


def test_set_values_still_writes_a_column(client, col, cid):
    resp = client.post("/v1/cards:set-values", json={"card_id": cid, "values": {"due": 77, "flags": 2}})
    assert resp.status_code == 200 and col.get_card(cid).due == 77 and col.get_card(cid).flags == 2


@pytest.mark.parametrize("operations,loc", [
    ([{"op": "suspend"}], ["body", "operations", 0, "cardIds"]),
    ([{"op": "set-flag", "card_ids": [1], "flag": 99}], ["body", "operations", 0, "flag"]),
    ([{"op": "nope"}], ["body", "operations", 0, "op"]),
    ([], ["body", "operations"]),
])
def test_a_bad_batch_step_is_a_422(client, operations, loc):
    resp = client.post("/v1/cards:batch", json={"operations": operations})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert isinstance(body["detail"], str) and [e["loc"] for e in body["errors"]] == [loc]


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/v1/notes", {"model_name": "Basic", "deck_name": "Default",
                           "fields": {"Front": "b", "Back": ""}, "tags": ["a b"]}),
    ("PATCH", "/v1/notes/{nid}", {"tags": ["ok", "a b"]}),
    ("PATCH", "/v1/notes/{nid}", {"add_tags": ["a\tb"]}),
    ("PATCH", "/v1/notes/{nid}", {"remove_tags": ["a b"]}),
    ("POST", "/v1/notes:upsert", [{"model_name": "Basic", "deck_name": "Default",
                                   "fields": {"Front": "c", "Back": ""}, "tags": ["a b"]}]),
])
def test_a_tag_with_a_space_is_refused(client, col, note, method, path, body):
    resp = client.request(method, path.format(nid=note), json=body)
    assert resp.status_code == 422, resp.text
    assert "space" in resp.json()["detail"]
    assert col.get_note(note).tags == []
