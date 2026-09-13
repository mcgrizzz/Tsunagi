"""
Full-app tests for /v1/reviews.

Seeded by answering cards through the real scheduler, so the rows under test
are revlog entries Anki actually wrote - intervals, ease factors and all.
"""
import pytest


def add_note(client, front, deck="Default"):
    return client.post("/v1/notes?include=cards", json={
        "modelName": "Basic", "deckName": deck,
        "fields": {"Front": front, "Back": "x"}}).json()["created"][0]


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


class TestNoDelete:
    """History can be imported (POST) but never removed through this resource."""

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


class TestInsert:
    def _card_id(self, client):
        add_note(client, "犬")
        return client.get("/v1/cards").json()["items"][0]["id"]

    def test_rows_round_trip(self, client):
        cid = self._card_id(client)
        rows = [
            {"id": 1700000000000, "card_id": cid, "usn": -1, "ease": 3,
             "interval": 1, "last_interval": 0, "factor": 2500,
             "time_ms": 4000, "type": 1},
            {"id": 1700000000001, "card_id": cid, "ease": 4},
        ]
        body = client.post("/v1/reviews", json={"reviews": rows}).json()
        assert body["inserted"] == 2
        got = client.get("/v1/reviews").json()["items"]
        assert [(r["id"], r["ease"], r["factor"]) for r in got] == [
            (1700000000000, 3, 2500), (1700000000001, 4, 0)]

    def test_wire_aliases_accepted(self, client):
        cid = self._card_id(client)
        body = client.post("/v1/reviews", json={"reviews": [
            {"id": 1700000000000, "cid": cid, "ivl": 3, "lastIvl": 1,
             "time": 2500, "ease": 2}]}).json()
        assert body["inserted"] == 1
        row = client.get("/v1/reviews").json()["items"][0]
        assert (row["card_id"], row["interval"], row["time_ms"]) == (cid, 3, 2500)

    def test_empty_list_inserts_nothing(self, client):
        assert client.post("/v1/reviews", json={"reviews": []}).json()["inserted"] == 0

    def test_duplicate_id_fails_and_rolls_back(self, client):
        cid = self._card_id(client)
        client.post("/v1/reviews", json={"reviews": [
            {"id": 1700000000000, "card_id": cid}]})
        resp = client.post("/v1/reviews", json={"reviews": [
            {"id": 1700000000001, "card_id": cid},
            {"id": 1700000000000, "card_id": cid}]})  # dupe of the first insert
        assert resp.status_code >= 400
        # All-or-nothing: the good row didn't land either.
        ids = [r["id"] for r in client.get("/v1/reviews").json()["items"]]
        assert ids == [1700000000000]

    def test_missing_required_field_is_422(self, client):
        resp = client.post("/v1/reviews", json={"reviews": [{"ease": 3}]})
        assert resp.status_code == 422

    def test_in_openapi(self, client):
        spec = client.get("/openapi.json").json()
        assert spec["paths"]["/v1/reviews"]["post"]["operationId"] == "createReviews"


class TestKeysetListing:
    def test_bare_listing_never_reads_the_whole_revlog(self, reviewed, col):
        # The scan tier walks the primary key with LIMIT; an unbounded
        # "select id from revlog" would be the old materialize-everything path.
        captured = []
        original = col.db.list
        col.db.list = lambda sql, *a: captured.append(sql) or original(sql, *a)
        body = reviewed.get("/v1/reviews", params={"limit": 2}).json()
        assert len(body["items"]) == 2
        id_queries = [s for s in captured if "from revlog" in s]
        assert id_queries and all("limit ?" in s for s in id_queries)

    def test_keyset_cursor_walks_every_review(self, reviewed):
        seen, cursor = [], None
        while True:
            params = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            body = reviewed.get("/v1/reviews", params=params).json()
            seen += [r["id"] for r in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert seen == sorted(seen) and len(seen) == 3

    def test_where_filter_rides_keyset(self, reviewed):
        body = reviewed.get("/v1/reviews", params={"where": "ease==3"}).json()
        assert len(body["items"]) == 3


class TestNativePageMeasurements:
    @pytest.mark.parametrize("resource", ["cards", "notes", "reviews"])
    @pytest.mark.parametrize("method", ["get", "post"])
    @pytest.mark.parametrize("projection", ["id", None])
    def test_first_two_pages_read_bounded_ids(self, reviewed, col, monkeypatch,
                                              resource, method, projection):
        """Measure real adapter SQL, including the continuation request."""
        # Grow beyond the hydration chunk so full enumeration is detectable.
        model = col.models.by_name("Basic")
        for index in range(503):
            note = col.new_note(model)
            note["Front"] = f"page measurement {index}"
            col.add_note(note, col.decks.id("Default"))
        first_review = col.db.first("select * from revlog order by id limit 1")
        for index in range(503):
            col.db.execute(
                "insert into revlog values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                first_review[0] + 10000 + index, *first_review[1:],
            )
        table = "revlog" if resource == "reviews" else resource
        expected = col.db.list(f"select id from {table} order by id limit 14")
        reads = []
        original = col.db.list
        hydrated = []
        backend_reads = []
        getter_name = {"cards": "get_card", "notes": "get_note"}.get(resource)
        if getter_name:
            original_get = getattr(col, getter_name)

            def measured_get(row_id):
                backend_reads.append(row_id)
                return original_get(row_id)

            monkeypatch.setattr(col, getter_name, measured_get)
        original_all = col.db.all

        def measured_all(sql, *args, **kwargs):
            rows = original_all(sql, *args, **kwargs)
            if f"from {table}" in sql.lower():
                hydrated.append((sql, len(rows)))
            return rows

        def measured(sql, *args, **kwargs):
            rows = original(sql, *args, **kwargs)
            if f"from {table}" in sql.lower():
                reads.append((sql, args, len(rows)))
            return rows

        def no_search(*args, **kwargs):
            pytest.fail("Unfiltered pagination must not materialize an Anki search")

        monkeypatch.setattr(col.db, "list", measured)
        monkeypatch.setattr(col.db, "all", measured_all)
        monkeypatch.setattr(col, "find_cards", no_search)
        monkeypatch.setattr(col, "find_notes", no_search)
        cursor = None
        seen = []
        for page in range(2):
            reads.clear()
            hydrated.clear()
            backend_reads.clear()
            query = {"limit": 7}
            if projection:
                query["select"] = projection
            if cursor:
                query["cursor"] = cursor
            if method == "get":
                response = reviewed.get(f"/v1/{resource}", params=query)
            else:
                response = reviewed.post(f"/v1/{resource}/query", json=query)
            assert response.status_code == 200, response.text
            body = response.json()
            seen.extend(body["items"] if projection else [row["id"] for row in body["items"]])
            cursor = body["next_cursor"]
            assert cursor
            assert reads, "Expected instrumentation to observe ID enumeration"
            assert sum(count for _, _, count in reads) <= 8, reads
            assert all("limit" in sql.lower() for sql, _, _ in reads), reads
            hydration_count = sum(count for _, count in hydrated) + len(backend_reads)
            assert 0 < hydration_count <= 7, (hydrated, backend_reads)
            print(f"{resource} {method} select={projection} page={page + 1}: "
                  f"id_queries={len(reads)}, ids_read={sum(r[2] for r in reads)}, "
                  f"rows_hydrated={hydration_count}, "
                  f"items={len(body['items'])}")
        assert seen == expected
