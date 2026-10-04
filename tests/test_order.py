"""order=: Anki's Browser sorts for cards and notes, fields elsewhere; ties in ascending id; paging."""
import pytest


@pytest.fixture()
def data(client, col, answer_cards):
    notes = [{"modelName": "Basic (and reversed card)" if i % 3 == 0 else "Basic", "deckName": "Default",
              "tags": ["even"] if i % 2 == 0 else [], "fields": {"Front": f"w{i:02}", "Back": "x"}}
             for i in range(12)]
    assert client.post("/v1/notes", json=notes).json()["failed"] == []
    answer_cards(5, "good")
    answer_cards(2, "again")
    return col


def walk(client, path, method="GET", **params):
    """Every row's id, a page of `limit` at a time when a limit is given."""
    out, params = [], dict(params)
    while True:
        if method == "GET":
            body = client.get(path, params=params).json()
        else:
            body = client.post(path + "/query", json=params).json()
        assert "items" in body, body
        out += [row["id"] for row in body["items"]]
        if not body["next_cursor"]:
            return out
        params["cursor"] = body["next_cursor"]


def anki_order(col, key, reverse, notes=False, query=""):
    column = {c.key: c for c in col.all_browser_columns()}[key]
    find = col.find_notes if notes else col.find_cards
    return [int(i) for i in find(query, order=column, reverse=reverse)]


@pytest.mark.parametrize("order,key,reverse", [
    ("interval:desc", "cardIvl", True), ("due", "cardDue", False), ("due:asc", "cardDue", False),
    ("reviews:desc", "cardReps", True), ("deck", "deck", False), ("sort_field:desc", "noteFld", True),
])
@pytest.mark.parametrize("limit", [None, 4])
def test_cards_follow_ankis_sort(client, data, order, key, reverse, limit):
    params = {"order": order, "select": "id", **({"limit": limit} if limit else {})}
    assert walk(client, "/v1/cards", **params) == anki_order(data, key, reverse)


@pytest.mark.parametrize("path,field,same_as", [
    ("/v1/cards", "reps", "reviews"), ("/v1/cards", "mod", "card_modified"),
    ("/v1/notes", "mod", "note_modified"), ("/v1/notes", "id", "created"),
])
def test_row_field_names_order_as_their_browser_sort(client, data, path, field, same_as):
    for direction in ("", ":desc"):
        rows = client.get(path, params={"order": field + direction, "select": f"id,{field}"}).json()["items"]
        assert [r["id"] for r in rows] == walk(client, path, order=same_as + direction, select="id")
        keys = [(r[field], r["id"]) for r in rows]   # ordered by the field, ties by id
        assert keys == sorted(keys, key=lambda k: (-k[0] if direction else k[0], k[1]))


def test_notes_follow_ankis_sort_with_a_search(client, data):
    expected = anki_order(data, "noteFld", True, notes=True, query="tag:even")
    assert walk(client, "/v1/notes", search="tag:even", order="sort_field:desc", limit=2, select="id") == expected
    assert walk(client, "/v1/notes", method="POST", search="tag:even", order="sort_field:desc", limit=2) == expected


def test_order_keeps_where_both_in_sql_and_python(client, data):
    everything = anki_order(data, "cardIvl", True)
    rows = {r["id"]: r for r in client.get("/v1/cards", params={"select": "id,reps,deck_name"}).json()["items"]}
    expected = [i for i in everything if rows[i]["reps"] >= 1 and rows[i]["deck_name"] == "Default"]
    got = walk(client, "/v1/cards", order="interval:desc", limit=3, select="id",
               where=["reps>=1", 'deck_name=="Default"'])   # the first in SQL, the second in Python
    assert got == expected and expected


def test_reviews_sort_by_field_with_ties_in_id(client, data):
    rows = client.get("/v1/reviews", params={"select": "id,interval,ease"}).json()["items"]
    by_interval = [r["id"] for r in sorted(sorted(rows, key=lambda r: r["id"]), key=lambda r: r["interval"], reverse=True)]
    assert walk(client, "/v1/reviews", order="interval:desc", limit=2, select="id") == by_interval
    assert walk(client, "/v1/reviews", order="id:desc", select="id") == sorted((r["id"] for r in rows), reverse=True)
    assert walk(client, "/v1/reviews", order="id:desc", where="ease==1", select="id") == sorted(
        (r["id"] for r in rows if r["ease"] == 1), reverse=True)


def test_small_resources_sort_by_their_fields(client, data):
    client.post("/v1/decks", json={"name": "Zeta"})
    client.post("/v1/decks", json={"name": "Alpha"})
    names = [r["name"] for r in client.get("/v1/decks", params={"order": "name:desc", "select": "name"}).json()["items"]]
    assert names == sorted(names, reverse=True) and "Zeta" in names
    decks = [r["name"] for r in client.get("/v1/decks", params={"order": "name", "limit": 1}).json()["items"]]
    assert decks == [min(names)]
    models = [r["name"] for r in client.get("/v1/models", params={"order": "name", "select": "name"}).json()["items"]]
    assert models == sorted(models)


@pytest.mark.parametrize("path,order,message", [
    ("/v1/cards", "question", "Can't order by question. Order by: card_modified"),
    ("/v1/cards", "factor", "Can't order by factor."),   # the ease sort puts new cards apart
    ("/v1/cards", "id", "Can't order by id."),           # no Browser sort by card id
    ("/v1/notes", "retrievability", "Can't order by retrievability."),   # a card-only sort
    ("/v1/reviews", "due", "Can't order by due. Order by: card_id"),
    ("/v1/cards", "due:sideways", "Invalid order 'due:sideways'"),
    ("/v1/decks", "nope", "Can't order by nope. Order by:"),
])
def test_what_cant_be_sorted_is_a_400(client, data, path, order, message):
    response = client.get(path, params={"order": order})
    assert response.status_code == 400, response.text
    assert response.json()["detail"].startswith(message)


def test_every_documented_sort_is_taken(client, data):
    # A field that is null on every row still sorts (6.101): no deck here has
    # its own limits or desired retention, yet the description lists them.
    spec = client.get("/openapi.json").json()
    for path, item in spec["paths"].items():
        for parameter in item.get("get", {}).get("parameters", []):
            for sort in parameter["schema"].get("x-sorts", []) if parameter["name"] == "order" else []:
                response = client.get(path, params={"order": f"{sort}:desc", "limit": 2})
                assert response.status_code == 200, (path, sort, response.text)


def test_a_cursor_survives_a_row_leaving_between_pages(client, data):
    first = client.get("/v1/cards", params={"order": "interval:desc", "limit": 3, "select": "id"}).json()
    order = anki_order(data, "cardIvl", True)
    data.sched.suspend_cards([order[5]])     # changes nothing about the sort
    data.remove_notes([data.get_card(order[3]).nid])
    rest = walk(client, "/v1/cards", order="interval:desc", select="id", cursor=first["next_cursor"])
    assert [r["id"] for r in first["items"]] + rest == anki_order(data, "cardIvl", True)[:3] + [
        i for i in anki_order(data, "cardIvl", True) if i not in order[:3]]
