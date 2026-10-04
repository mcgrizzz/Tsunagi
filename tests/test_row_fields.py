"""Row fields say what they mean, not what Anki happens to store (backlog 6.102)."""


def _add_card(client, col):
    client.post("/v1/notes", json={"modelName": "Basic", "deckName": "Default",
                                   "fields": {"Front": "a", "Back": "b"}})
    return col.find_cards("")[0]


def _deck(client, did=1):
    return client.get("/v1/decks", params={"where": f"id=={did}"}).json()["items"][0]


def test_card_left_drops_old_schedulers_packed_count(client, col):
    cid = _add_card(client, col)
    col.db.execute("update cards set left = 1002 where id = ?", cid)
    # The SQL path (select, where) and the full row agree on 2.
    assert client.get("/v1/cards", params={"where": "left==2", "select": "id,left"}).json()["items"] == [
        {"id": cid, "left": 2}]
    assert client.get("/v1/cards", params={"where": "left>=1000"}).json()["items"] == []
    assert client.get("/v1/cards").json()["items"][0]["left"] == 2


def test_removed_fields_are_unknown(client, col):
    _add_card(client, col)
    for path, field in (("/v1/cards", "flags"), ("/v1/models", "did"), ("/v1/models", "tags"),
                        ("/v1/models", "vers"), ("/v1/decks", "new_today"), ("/v1/decks", "learn_today")):
        assert client.get(path, params={"select": field}).status_code == 400, (path, field)
    model = client.get("/v1/models", params={"where": "name==Basic"}).json()["items"][0]
    assert {"did", "tags", "vers"}.isdisjoint(model)
    assert all("media" not in f for f in model["fields"])
    # A template's own deck override is a different, live field.
    assert "did" in model["templates"][0]


def test_deck_counts_only_count_today(client, col):
    today = col.sched.today
    stale = col.decks.id("Stale")
    for did, day in ((1, today), (stale, today + 1)):
        deck = col.decks.get(did)
        deck["newToday"], deck["revToday"], deck["timeToday"] = [day, 3], [day, 9], [day, 1234]
        col.decks.update_dict(deck)

    rows = {d["id"]: d for d in client.get("/v1/decks").json()["items"]}
    fields = ("new_limit_used", "review_limit_used", "study_ms_today")
    assert [rows[1][f] for f in fields] == [3, 9, 1234]
    assert [rows[stale][f] for f in fields] == [0, 0, 0]

    # Custom Study's "increase today's limit" subtracts from the count.
    col.decks.select(1)
    col.sched.extend_limits(5, 0)
    assert _deck(client)["new_limit_used"] == -2


def test_deck_day_limits_only_on_their_day(client, col):
    today = col.sched.today
    deck = col._backend.get_deck(1)
    deck.normal.review_limit_today.limit, deck.normal.review_limit_today.today = 7, today
    deck.normal.new_limit_today.limit, deck.normal.new_limit_today.today = 4, today + 1
    col._backend.update_deck(deck)
    row = _deck(client)
    assert (row["review_limit_today"], row["new_limit_today"]) == (7, None)
    assert client.get("/v1/decks", params={"where": "review_limit_today==7", "select": "id"}).json()[
        "items"] == [{"id": 1}]
