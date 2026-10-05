"""distinct_on=: one row per distinct value of a field, the first in `order` (backlog 8.12)."""
import pytest


@pytest.fixture()
def data(client, col, answer_cards):
    notes = [{"noteTypeName": "Basic (and reversed card)" if i % 3 == 0 else "Basic", "deckName": "Default",
              "fields": {"Front": f"w{i:02}", "Back": "x"}} for i in range(9)]
    assert client.post("/v1/notes", json=notes).json()["failed"] == []
    for _ in range(3):   # several reviews per card, some of them Again
        answer_cards(6, "good")
        answer_cards(3, "again")
    return col


def walk(client, path, **params):
    out = []
    while True:
        body = client.get(path, params=params).json()
        assert "items" in body, body
        out += body["items"]
        if not body["next_cursor"]:
            return out
        params["cursor"] = body["next_cursor"]


def latest(col, where=""):
    """Each card's newest review id, from the revlog itself."""
    return col.db.list(f"select max(id) from revlog {where} group by cid order by max(id) desc")


@pytest.mark.parametrize("limit", [None, 2])
def test_each_cards_latest_review(client, data, limit):
    rows = walk(client, "/v1/reviews", distinct_on="card_id", order="id:desc",
                select="id,card_id,interval", **({"limit": limit} if limit else {}))
    assert [r["id"] for r in rows] == latest(data)
    assert len({r["card_id"] for r in rows}) == len(rows)
    for r in rows:   # the interval AnkiConnect's getIntervals reports for that card
        assert r["interval"] == data.db.scalar("select ivl from revlog where id=?", r["id"])


def test_where_applies_before_the_pick(client, data):
    rows = walk(client, "/v1/reviews", distinct_on="card_id", order="id:desc", where="rating==1", select="id")
    assert [r["id"] for r in rows] == latest(data, "where ease = 1") and rows


def test_with_a_search(client, data):
    cid = data.db.scalar("select cid from revlog order by id limit 1")
    rows = walk(client, "/v1/reviews", search=f"cid:{cid}", distinct_on="card_id", order="id:desc", select="id")
    assert [r["id"] for r in rows] == [data.db.scalar("select max(id) from revlog where cid=?", cid)]


def test_without_order_the_first_by_id(client, data):
    cards = walk(client, "/v1/cards", distinct_on="note_id", select="id,note_id")
    assert [c["id"] for c in cards] == data.db.list("select min(id) from cards group by nid order by min(id)")


def test_with_a_browser_sort_and_the_post_form(client, data):
    expected = []
    seen = set()
    for row in walk(client, "/v1/cards", order="interval:desc", select="id,note_id"):
        if row["note_id"] not in seen:
            seen.add(row["note_id"])
            expected.append(row["id"])
    body = client.post("/v1/cards/query", json={"order": "interval:desc", "distinct_on": "note_id",
                                                 "select": "id"}).json()
    assert [c["id"] for c in body["items"]] == expected


def test_notes_and_small_resources(client, data):
    notes = walk(client, "/v1/notes", distinct_on="note_type_id", select="id,note_type_id")
    assert sorted(n["note_type_id"] for n in notes) == sorted(set(data.db.list("select mid from notes")))
    client.post("/v1/decks", json={"name": "Second"})
    decks = walk(client, "/v1/decks", distinct_on="preset_id", select="id,preset_id")
    assert len(decks) == 1 and decks[0]["id"] == min(d["id"] for d in walk(client, "/v1/decks", select="id"))


@pytest.mark.parametrize("path,params,message", [
    ("/v1/cards", {"distinct_on": "deck_name"}, "Can't use distinct_on with deck_name. Use: "),
    ("/v1/reviews", {"distinct_on": "card_id", "where": "card_id~=1"}, "distinct_on can't be combined"),
    ("/v1/cards", {"distinct_on": "note_id", "where": 'deck_name=="Default"'}, "distinct_on can't be combined"),
    ("/v1/decks", {"distinct_on": "nope"}, "Can't use distinct_on with nope. Use: "),
])
def test_what_cant_be_picked_is_a_400(client, data, path, params, message):
    response = client.get(path, params=params)
    assert response.status_code == 400, response.text
    assert response.json()["detail"].startswith(message)


def test_cards_with_a_search_by_id(client, data):
    # A search's ids, grouped a chunk at a time (cards have no search condition in SQL).
    cards = walk(client, "/v1/cards", search="deck:Default", distinct_on="note_id", select="id")
    assert [c["id"] for c in cards] == data.db.list("select min(id) from cards group by nid order by min(id)")


def test_reviews_by_another_order(client, data):
    rows = walk(client, "/v1/reviews", distinct_on="card_id", order="interval:desc", select="id,card_id,interval")
    expected, seen = [], set()
    for r in data.db.all("select id, cid from revlog order by ivl desc, id"):
        if r[1] not in seen:
            seen.add(r[1])
            expected.append(r[0])
    assert [r["id"] for r in rows] == expected
