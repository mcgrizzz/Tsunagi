"""
Full-app tests for /v1/reviews.

Seeded by answering cards through the real scheduler, so the rows under test
are revlog entries Anki actually wrote - intervals, ease factors and all.
"""
import pytest


def add_note(client, front, deck="Default"):
    return client.post("/v1/notes", json={
        "modelName": "Basic", "deckName": deck,
        "fields": {"Front": front, "Back": "x"}}).json()["result"]


@pytest.fixture()
def reviewed(client, col, answer_cards):
    """Three notes in JP, all three answered once."""
    deck_id = client.post("/v1/decks", json={"name": "JP"}).json()["result"]["id"]
    for front in ("犬", "猫", "鳥"):
        add_note(client, front, deck="JP")
    # The scheduler's queue is scoped to the selected deck, not the collection.
    col.decks.select(deck_id)
    assert answer_cards(3) == 3
    return client


class TestReads:
    def test_bare_list_uses_human_field_names(self, reviewed):
        body = reviewed.get("/v1/reviews").json()
        assert len(body["items"]) == 3
        row = body["items"][0]
        assert {"id", "card_id", "ease", "interval", "last_interval",
                "factor", "time_ms", "type"} <= set(row)
        assert "cid" not in row and "ivl" not in row and "lastIvl" not in row

    def test_rows_describe_a_real_review(self, reviewed):
        row = reviewed.get("/v1/reviews").json()["items"][0]
        assert row["ease"] == 3                  # "good" is button 3
        assert row["id"] > 1_500_000_000_000     # epoch ms, not seconds
        assert row["time_ms"] >= 0

    def test_ordered_by_review_time(self, reviewed):
        ids = [r["id"] for r in reviewed.get("/v1/reviews").json()["items"]]
        assert ids == sorted(ids)

    def test_empty_collection_has_no_reviews(self, client):
        assert client.get("/v1/reviews").json()["items"] == []

    def test_select_projects(self, reviewed):
        rows = reviewed.get("/v1/reviews", params={
            "select": "id,ease", "shape": "object"}).json()["items"]
        assert all(set(r) == {"id", "ease"} for r in rows)

    def test_where_filters(self, reviewed):
        assert reviewed.get("/v1/reviews", params={
            "where": "ease==1"}).json()["items"] == []
        assert len(reviewed.get("/v1/reviews", params={
            "where": "ease==3"}).json()["items"]) == 3


class TestIndices:
    def test_id_index(self, reviewed):
        rid = reviewed.get("/v1/reviews").json()["items"][1]["id"]
        body = reviewed.get("/v1/reviews", params={"where": f"id=={rid}"}).json()
        assert [r["id"] for r in body["items"]] == [rid]

    def test_card_id_index(self, reviewed):
        first = reviewed.get("/v1/reviews").json()["items"][0]
        body = reviewed.get("/v1/reviews", params={
            "where": f"card_id=={first['card_id']}"}).json()
        assert [r["card_id"] for r in body["items"]] == [first["card_id"]]

    def test_card_id_index_avoids_search(self, reviewed, col):
        cid = reviewed.get("/v1/reviews").json()["items"][0]["card_id"]
        calls = []
        original = col.find_cards
        col.find_cards = lambda q, **kw: calls.append(q) or original(q, **kw)
        reviewed.get("/v1/reviews", params={"where": f"card_id=={cid}"})
        assert calls == []


class TestSearch:
    def test_search_scopes_to_matching_cards(self, reviewed, client):
        assert len(reviewed.get("/v1/reviews", params={
            "search": "deck:JP"}).json()["items"]) == 3
        # A deck with cards but no reviews contributes nothing.
        client.post("/v1/decks", json={"name": "Other"})
        add_note(client, "馬", deck="Other")
        assert reviewed.get("/v1/reviews", params={
            "search": "deck:Other"}).json()["items"] == []

    def test_search_matching_no_cards_is_empty(self, reviewed):
        assert reviewed.get("/v1/reviews", params={
            "search": "deck:NoSuchDeck"}).json()["items"] == []

    def test_malformed_search_is_400(self, reviewed):
        assert reviewed.get("/v1/reviews",
                            params={"search": '"unbalanced'}).status_code == 400


class TestPagination:
    def test_cursor_walks_every_row(self, reviewed):
        seen, cursor = [], None
        while True:
            params = {"limit": 1}
            if cursor:
                params["cursor"] = cursor
            body = reviewed.get("/v1/reviews", params=params).json()
            seen += [r["id"] for r in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert seen == sorted(seen) and len(seen) == 3

    def test_limit_counts_returned_items(self, reviewed):
        body = reviewed.get("/v1/reviews", params={"limit": 2}).json()
        assert len(body["items"]) == 2 and body["next_cursor"] is not None


class TestPageHydratesAPage:
    """
    Regression: /v1/reviews shipped with a `fetch_all`, which put the planner
    on the "full" tier - it built a ReviewInfo for every row in the revlog to
    return a page of five. On a real collection (120k reviews) a bare listing
    took 1.2 SECONDS. Cards and notes supply no fetch_all for exactly this
    reason; reviews must not either.
    """

    def _parses_during(self, client, monkeypatch, url):
        from tsunagi.shared.schemas import reviews as schema

        count = {"n": 0}
        original = schema.ReviewInfo.parse_obj

        def counting(obj):
            count["n"] += 1
            return original(obj)

        monkeypatch.setattr(schema.ReviewInfo, "parse_obj", counting)
        client.get(url)
        return count["n"]

    def test_bare_listing_hydrates_only_the_page(self, client, col, answer_cards,
                                                 monkeypatch):
        deck_id = client.post("/v1/decks", json={"name": "JP"}).json()["result"]["id"]
        for i in range(12):
            add_note(client, f"q{i}", deck="JP")
        col.decks.select(deck_id)
        assert answer_cards(12) == 12

        parsed = self._parses_during(client, monkeypatch, "/v1/reviews?limit=3")
        assert parsed == 3, (
            f"hydrated {parsed} rows to return 3 - the planner is materializing "
            "the whole revlog again"
        )

    def test_caps_expose_no_fetch_all(self):
        from tsunagi.http.v1.reviews import caps

        assert caps.fetch_all is None


class TestReadOnly:
    """The scheduler owns the revlog; there is no way in through this resource."""

    def test_no_create_route(self, reviewed):
        assert reviewed.post("/v1/reviews", json={"card_id": 1}).status_code == 405

    def test_no_delete_route(self, reviewed):
        rid = reviewed.get("/v1/reviews").json()["items"][0]["id"]
        assert reviewed.delete(f"/v1/reviews/{rid}").status_code in (404, 405)


class TestFsrs:
    def test_a_review_gives_the_card_fsrs_memory_state(self, client, col, answer_cards):
        # Ties the two resources together: answering a card writes a revlog row
        # AND gives the card the memory state /v1/cards reports. FSRS shipped
        # in 23.10, our floor, and has been the default since 24.11.
        col.set_config("fsrs", True)
        add_note(client, "犬")
        assert answer_cards(1) == 1

        (review,) = client.get("/v1/reviews").json()["items"]
        card = client.get("/v1/cards", params={
            "where": f"id=={review['card_id']}", "shape": "object"}).json()["items"][0]
        assert card["memory_state"] is not None
        assert card["memory_state"]["stability"] > 0
        assert card["memory_state"]["difficulty"] > 0
