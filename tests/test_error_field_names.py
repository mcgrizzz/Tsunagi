"""
A 422 names fields as the API description does (backlog 6.78): pydantic
reports locations by alias, so `add_tags` came back as `addTags`.
"""
import pytest


@pytest.fixture()
def note(client):
    return client.post("/v1/notes", json={"note_type_name": "Basic", "deck_name": "Default",
                                          "fields": {"Front": "a", "Back": ""}}).json()["created"][0]["id"]


@pytest.mark.parametrize("method,path,body,loc", [
    ("PATCH", "/v1/notes/{nid}", {"add_tags": ["a b"]}, ["body", "add_tags"]),
    ("POST", "/v1/cards:suspend", {"cardIds": "x"}, ["body", "card_ids"]),     # the alias, sent
    ("POST", "/v1/reviews", {"reviews": [{"id": 1, "cid": "x"}]}, ["body", "reviews", 0, "card_id"]),
    ("POST", "/v1/notes:upsert", [{"note_type_name": "Basic", "deck_name": "Default", "fields": {"Front": "x"},
                                   "allowDuplicate": "maybe"}], ["body", 0, "allow_duplicate"]),
    ("POST", "/v1/cards:batch", {"operations": [{"op": "suspend"}]}, ["body", "operations", 0, "card_ids"]),
    ("POST", "/v1/cards:batch", {"operations": [{"op": "reposition", "card_ids": [1], "startingFrom": "x"}]},
     ["body", "operations", 0, "starting_from"]),
])
def test_a_422_names_the_field(client, note, method, path, body, loc):
    resp = client.request(method, path.format(nid=note), json=body)
    assert resp.status_code == 422, resp.text
    assert loc in [e["loc"] for e in resp.json()["errors"]]
    assert ".".join(map(str, loc)) in resp.json()["detail"]


def test_a_field_without_an_alias_is_unchanged(client):
    resp = client.post("/v1/cards:set-flag", json={"card_ids": [1], "flag": "x"})
    assert resp.status_code == 422 and ["body", "flag"] in [e["loc"] for e in resp.json()["errors"]]
