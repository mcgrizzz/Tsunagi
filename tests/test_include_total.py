"""include=total: how many rows the query matches, across all pages (backlog 8.1)."""
import pytest


@pytest.fixture()
def data(client, col, answer_cards):
    notes = [{"modelName": "Basic (and reversed card)" if i % 3 == 0 else "Basic",
              "deckName": "Default" if i % 2 else "Mining", "tags": ["even"] if i % 2 == 0 else [],
              "fields": {"Front": f"w{i:02}", "Back": "x"}} for i in range(10)]
    client.post("/v1/decks", json={"name": "Mining"})
    assert client.post("/v1/notes", json=notes).json()["failed"] == []
    answer_cards(6, "good")
    answer_cards(3, "again")
    return col


def every(client, path, **params):
    """All matching rows, the slow way: unpaged, ids only."""
    return client.get(path, params={**params, "select": "id"}).json()["items"]


@pytest.mark.parametrize("path,params", [
    ("/v1/cards", {}),                                        # count(*)
    ("/v1/cards", {"search": "deck:Mining"}),                 # the search's ids
    ("/v1/cards", {"where": "reps>=1"}),                      # count(*) with the clause in SQL
    ("/v1/cards", {"search": "tag:even", "where": "reps>=1"}),
    ("/v1/cards", {"where": 'deck_name=="Default"'}),         # not a column: counted from the rows
    ("/v1/notes", {"where": "first_field==\"w03\""}),         # a checksum superset: counted from the rows
    ("/v1/reviews", {"search": "deck:Mining"}),               # reviews: the search as cid in (...)
    ("/v1/reviews", {"distinct_on": "card_id"}),
    ("/v1/reviews", {"search": "deck:Default", "distinct_on": "card_id", "where": "ease==1"}),
    ("/v1/decks", {}),
    ("/v1/models", {"where": 'name~="basic"'}),
])
def test_total_is_every_matching_row(client, data, path, params):
    body = client.get(path, params={**params, "include": "total", "limit": 2}).json()
    assert body["total"] == len(every(client, path, **params)), body
    assert len(body["items"]) == min(2, body["total"])


def test_the_same_total_on_every_page(client, data):
    params = {"include": "total", "limit": 3, "select": "id"}
    totals = []
    while True:
        body = client.get("/v1/cards", params=params).json()
        totals.append(body["total"])
        if not body["next_cursor"]:
            break
        params["cursor"] = body["next_cursor"]
    assert len(set(totals)) == 1 and len(totals) > 1


def test_limit_zero_is_the_count_alone(client, data):
    body = client.get("/v1/cards", params={"include": "total", "limit": 0}).json()
    assert body["items"] == [] and body["next_cursor"] is None
    assert body["total"] == data.card_count()
    body = client.post("/v1/notes/query", json={"include": "total", "limit": 0}).json()
    assert body["items"] == [] and body["total"] == data.note_count()


def test_without_include_there_is_no_total(client, data):
    assert "total" not in client.get("/v1/cards", params={"limit": 1}).json()
    assert "total" not in client.get("/v1/decks").json()


def test_a_bad_search_is_still_a_400(client, data):
    r = client.get("/v1/cards", params={"search": "deck:(", "include": "total", "limit": 0})
    assert r.status_code == 400


@pytest.mark.parametrize("method,path,kwargs", [
    ("get", "/v1/cards", {"params": {"include": "totals"}}),
    ("post", "/v1/cards/query", {"json": {"include": "total,cards"}}),
    ("post", "/v1/notes:upsert", {"params": {"include": "duplicate_ids"},
                                  "json": {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "x"},
                                           "match": {"field": "Front"}}}),
])
def test_an_unknown_part_is_a_422_naming_what_include_takes(client, data, method, path, kwargs):
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 422, response.text
    assert "include takes:" in response.json()["detail"]
