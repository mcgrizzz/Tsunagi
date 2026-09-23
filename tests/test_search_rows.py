"""A complete, unfiltered search reads rows once; everything else pages ids."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tsunagi.shared.planning import SearchSpec, SourceCaps
from tsunagi.shared.route_factory import ModelRow, create_resource_routes
from tsunagi.shared.schemas.wrappers import Paginated


@pytest.fixture
def source():
    rows = {i: {"id": i, "kind": "even" if i % 2 == 0 else "odd"} for i in range(1, 401)}
    calls = {"find": 0, "hydrate": 0, "rows": 0}

    def matching(query):
        return [i for i in rows if not query or rows[i]["kind"] == query]

    def find_ids(query):
        calls["find"] += 1
        return list(reversed(matching(query)))   # enumeration order is not the result order

    def hydrate(ids, wants=None):
        calls["hydrate"] += 1
        return [rows[i] for i in ids if i in rows]

    def search_rows(query, wants=None):
        calls["rows"] += 1
        return [rows[i] for i in sorted(matching(query))]

    app = FastAPI()
    app.include_router(create_resource_routes(
        "/things", caps=SourceCaps(search=SearchSpec(find_ids=find_ids, hydrate=hydrate, rows=search_rows)),
        response_model=Paginated[ModelRow], resource_name="thing", resource_plural="things", tag="Things",
    ))
    with TestClient(app) as client:
        yield client, calls


@pytest.mark.parametrize("query", [{}, {"search": "even"}, {"search": "odd", "select": "id"}])
def test_complete_unfiltered_result_uses_one_read(source, query):
    client, calls = source
    body = client.get("/things", params=query).json()
    assert calls == {"find": 0, "hydrate": 0, "rows": 1}
    assert body["next_cursor"] is None and len(body["items"]) in (200, 400)


@pytest.mark.parametrize("query", [
    {"search": "even", "limit": 7},
    {"search": "even", "where": "id>300"},
    {"limit": 5},
])
def test_paged_or_filtered_results_keep_id_enumeration(source, query):
    client, calls = source
    one_pass = client.get("/things", params={k: v for k, v in query.items() if k == "search"}).json()["items"]
    calls.update(find=0, hydrate=0, rows=0)
    body = client.get("/things", params=query).json()
    assert calls["rows"] == 0 and calls["hydrate"] >= 1
    expected = [r for r in one_pass if "where" not in query or r["id"] > 300][:query.get("limit")]
    assert body["items"] == expected
