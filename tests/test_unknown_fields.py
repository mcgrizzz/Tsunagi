"""
A field a list doesn't have is a 400 naming the ones it does (backlog 6.77).
`select=ivl` on cards used to answer {"ivl": null}, and `where=ivl>=0` matched
nothing, so a guessed name looked like an empty result.
"""
import pytest


@pytest.fixture()
def note(client):
    return client.post("/v1/notes", json={"model_name": "Basic", "deck_name": "Default",
                                          "fields": {"Front": "a", "Back": ""}}).json()["created"][0]["id"]


@pytest.mark.parametrize("params,name", [
    ({"select": "ivl"}, "ivl"),
    ({"select": "id,ivl"}, "ivl"),
    ({"select": "nope[].name"}, "nope"),
    ({"where": "ivl>=0"}, "ivl"),
    ({"where": ["interval>=0", "nid==1"]}, "nid"),
    ({"select": "id", "shape": "scalar", "where": "ivl>=0"}, "ivl"),
])
def test_an_unknown_card_field_is_a_400(client, note, params, name):
    resp = client.get("/v1/cards", params=params)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert f"Unknown field {name}." in detail and "interval" in detail


def test_the_post_query_checks_too(client, note):
    resp = client.post("/v1/reviews/query", json={"select": "cid,ivl"})
    assert resp.status_code == 400 and "card_id" in resp.json()["detail"]


@pytest.mark.parametrize("path,params", [
    ("/v1/cards", {"select": "id,interval,memory_state", "where": "interval>=0"}),
    ("/v1/notes", {"select": "fields[].name,fields[name in [\"Front\"]].value", "where": "fields[].name==\"Front\""}),
    ("/v1/decks", {"select": "name,new_count"}),
    ("/v1/tags", {"select": "name"}),
    ("/v1/media", {"select": "filename,size"}),
    # Deck presets are Anki's own settings, whose names vary by version.
    ("/v1/deck-configs", {"select": "id,new,maxTaken"}),
])
def test_known_fields_still_answer(client, note, path, params):
    resp = client.get(path, params=params)
    assert resp.status_code == 200, resp.text


def test_a_malformed_select_keeps_its_own_message(client, note):
    resp = client.get("/v1/cards", params={"select": "id,("})
    assert resp.status_code == 400 and "Unknown field" not in resp.json()["detail"]
