"""
Ordered review pages resume from the last row sent (backlog 8.1b): each page
asks SQL for the rows after it, instead of sorting every review again.
"""
import base64
import json

import pytest


@pytest.fixture()
def cards(client, col):
    nids = [client.post("/v1/notes", json={"note_type_name": "Basic", "deck_name": "Default",
                                           "fields": {"Front": f"n{i}", "Back": ""}}).json()["created"][0]["id"]
            for i in range(2)]
    cids = [col.card_ids_of_note(n)[0] for n in nids]
    # Many ties in interval and ease, so the order depends on ties by id.
    rows = [{"id": 1700000000000 + i, "card_id": cids[i % 2], "rating": 1 + i % 4,
             "interval": (i * 7) % 5, "ease_factor": 2500, "duration_ms": 1000 + i}
            for i in range(53)]
    assert client.post("/v1/reviews", json={"reviews": rows}).status_code == 200
    return cids


def walk(client, query, limit=7):
    ids, cursor = [], None
    while True:
        page = client.get("/v1/reviews", params={**query, "limit": limit, "select": "id",
                                                 **({"cursor": cursor} if cursor else {})})
        assert page.status_code == 200, page.text
        ids += [r["id"] for r in page.json()["items"]]
        cursor = page.json()["next_cursor"]
        if cursor is None:
            return ids


QUERIES = [
    {"order": "interval"},
    {"order": "interval:desc"},
    {"order": "rating:desc", "where": "interval>=2"},
    {"order": "duration_ms:desc"},
    {"order": "id:desc"},
]


@pytest.mark.parametrize("query", QUERIES, ids=[str(q) for q in QUERIES])
def test_pages_follow_the_unpaged_order(client, cards, query):
    whole = [r["id"] for r in client.get("/v1/reviews", params={**query, "select": "id"}).json()["items"]]
    assert walk(client, query) == whole
    assert len(set(whole)) == len(whole) > 7


def test_pages_follow_the_order_with_a_search(client, cards):
    query = {"order": "interval:desc", "search": f"cid:{cards[0]}"}
    whole = [r["id"] for r in client.get("/v1/reviews", params={**query, "select": "id"}).json()["items"]]
    assert walk(client, query, limit=4) == whole and len(whole) == 27


def test_ties_come_in_ascending_id(client, cards):
    rows = client.get("/v1/reviews", params={"order": "interval:desc", "select": "id,interval"}).json()["items"]
    assert rows == sorted(rows, key=lambda r: (-r["interval"], r["id"]))


def test_a_page_reads_only_its_rows(client, col, cards, monkeypatch):
    # The old way sorted every review on each page: no limit in the SQL.
    seen = []
    for name in ("list", "all"):
        real = getattr(col.db, name)
        monkeypatch.setattr(col.db, name, lambda sql, *a, _real=real: seen.append(sql) or _real(sql, *a))
    first = client.get("/v1/reviews", params={"order": "interval", "limit": 5, "select": "id"}).json()
    client.get("/v1/reviews", params={"order": "interval", "limit": 5, "select": "id",
                                      "cursor": first["next_cursor"]})
    ordered = [q for q in seen if "from revlog" in q and "order by" in q and "id in (" not in q]
    assert ordered and all("limit" in q for q in ordered), ordered


def test_the_last_page_has_no_cursor(client, cards):
    page = client.get("/v1/reviews", params={"order": "interval", "limit": 53}).json()
    assert len(page["items"]) == 53 and page["next_cursor"] is None


def test_a_cursor_from_another_kind_of_page_is_refused(client, cards):
    position = base64.urlsafe_b64encode(json.dumps({"pos": 5, "last": 1}).encode()).decode().rstrip("=")
    resp = client.get("/v1/reviews", params={"order": "interval", "cursor": position})
    assert resp.status_code == 400
