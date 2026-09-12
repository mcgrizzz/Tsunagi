"""Unlimited reads by default, explicit pages, and consistent GET/POST discovery."""
from types import SimpleNamespace

import pytest

from tsunagi.shared.pagination import encode_cursor, paginate_keyset
from tsunagi.shared.route_factory import _paged_scan
from tsunagi.shared.schemas.wrappers import QueryRequest


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("limit", [0, -1])
def test_query_limit_still_requires_positive_value(client, method, limit):
    response = (client.get("/v1/cards", params={"limit": limit}) if method == "GET" else
                client.post("/v1/cards/query", json={"limit": limit}))
    assert response.status_code == 422


def test_query_limit_discovery_has_no_numeric_default_or_maximum(client):
    schema = client.get("/openapi.json").json()
    limits = [schema["components"]["schemas"]["QueryRequest"]["properties"]["limit"]]
    for path in ("/v1/cards", "/v1/notes", "/v1/models", "/v1/decks", "/v1/reviews", "/v1/media"):
        limits.append(next(p["schema"] for p in schema["paths"][path]["get"]["parameters"]
                           if p["name"] == "limit"))
    for limit in limits:
        assert limit.get("default") is None
        assert limit["minimum"] == 1
        assert "maximum" not in limit


def test_media_omitted_limit_returns_all_and_explicit_limit_keeps_cursor(client, monkeypatch):
    from tsunagi.http.v1 import media
    files = [(f"file-{index:05}.png", 12, 0) for index in range(6002)]
    monkeypatch.setattr(media, "list_media", lambda: files)
    default = client.get("/v1/media").json()
    assert len(default["items"]) == 6002
    assert default["next_cursor"] is None

    response = client.get("/v1/media", params={"limit": 6001})
    assert response.status_code == 200
    page = response.json()
    assert [item["filename"] for item in page["items"]] == [f[0] for f in files[:6001]]
    last = client.get("/v1/media", params={"cursor": page["next_cursor"]}).json()
    assert [item["filename"] for item in last["items"]] == [files[-1][0]]
    assert last["next_cursor"] is None


@pytest.mark.parametrize("source", ["keyset", "search"])
@pytest.mark.parametrize("filtered", [False, True])
@pytest.mark.parametrize("after", [None, 501, 6001])
def test_omitted_limit_scans_all_remaining_matches_in_chunks(source, filtered, after):
    ids = list(range(1, 6002))
    hydrated = []

    def hydrate(batch, wants):
        assert len(batch) <= 250
        hydrated.append((list(batch), wants))
        return [{"id": i, "value": i % 3} for i in batch]

    def page_ids(key, size):
        assert size <= 250
        return [i for i in ids if key is None or i > key][:size]

    plan = SimpleNamespace(find_ids=lambda: ids, hydrate=hydrate,
                           page_ids=page_ids if source == "keyset" else None)
    predicate = (lambda row: row["value"] == 0) if filtered else None
    rows, cursor = _paged_scan(
        plan, None, encode_cursor({"last_key": after}) if after else None,
        None, lambda row: row["id"], predicate, {"value"} if filtered else None,
    )
    expected = [i for i in ids if (after is None or i > after) and (not filtered or i % 3 == 0)]
    assert [r["id"] for r in rows] == expected
    assert cursor is None
    if filtered and expected:
        assert any(wants == {"value"} for _, wants in hydrated)
        assert any(wants is None for _, wants in hydrated)


def test_in_memory_pagination_omitted_limit_returns_all_remaining():
    items = [{"id": i} for i in range(1501)]
    first, cursor = paginate_keyset(items, 7, None, lambda row: row["id"])
    rest, end = paginate_keyset(iter(items), None, cursor, lambda row: row["id"])
    assert first + rest == items
    assert end is None
    assert QueryRequest().limit is None


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_query_routes_pass_omitted_limit_as_unlimited(client, monkeypatch, method):
    from tsunagi.shared import route_factory

    def execute_query(**kwargs):
        assert kwargs["limit"] is None
        return {"items": list(range(1201)), "next_cursor": None, "stats": {}}

    monkeypatch.setattr(route_factory, "_execute_query", execute_query)
    response = (client.get("/v1/cards") if method == "GET" else
                client.post("/v1/cards/query", json={}))
    assert response.status_code == 200
    assert response.json()["items"] == list(range(1201))
    assert response.json()["next_cursor"] is None
