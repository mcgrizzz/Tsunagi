"""ID projections use authoritative search results, never unverified input IDs."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tsunagi.shared.planning import IndexSpec, SearchSpec, SourceCaps
from tsunagi.shared.route_factory import ModelRow, create_resource_routes
from tsunagi.shared.schemas.wrappers import Paginated


@pytest.fixture
def source():
    rows = {i: {"id": i, "name": "even" if i % 2 == 0 else "odd"} for i in range(1, 604)}
    calls = {"search": [], "pages": [], "hydrate": []}

    def find_ids(query):
        calls["search"].append(query)
        return [i for i in reversed(rows) if not query or rows[i]["name"] == query]

    def page_ids(after, limit):
        calls["pages"].append((after, limit))
        return [i for i in sorted(rows) if after is None or i > after][:limit]

    def hydrate(ids, wants=None):
        calls["hydrate"].append((list(ids), wants))
        return [rows[i] for i in ids if i in rows]

    caps = SourceCaps(
        indices=[IndexSpec(path=("id",), fetch_values=hydrate, coerce=int)],
        search=SearchSpec(find_ids=find_ids, hydrate=hydrate, page_ids=page_ids, id_field="id"),
    )
    app = FastAPI()
    app.include_router(create_resource_routes(
        "/things", caps=caps, response_model=Paginated[ModelRow],
        resource_name="thing", resource_plural="things", tag="Things",
    ))
    with TestClient(app) as client:
        yield client, rows, calls


def request(client, method, query):
    response = (client.get("/things", params=query) if method == "GET"
                else client.post("/things/query", json=query))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("search", [None, "", "even"])
def test_ids_and_filtered_pagination_need_no_record_loads(source, method, search):
    client, rows, calls = source
    query = {"select": "id", "where": ["id > 500"], "limit": 17}
    if search is not None:
        query["search"] = search
    result = []
    while True:
        page = request(client, method, query)
        result.extend(page["items"])
        if page["next_cursor"] is None:
            break
        query["cursor"] = page["next_cursor"]
    assert result == [i for i in rows if i > 500 and (search != "even" or i % 2 == 0)]
    assert calls["hydrate"] == []
    assert calls["pages"] if search is None else calls["search"]


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_id_projection_is_live_and_preserves_object_shape(source, method):
    client, rows, calls = source
    query = {"search": "even", "select": "id", "shape": "object"}
    assert request(client, method, query)["items"] == [{"id": i} for i in rows if i % 2 == 0]
    del rows[2]
    rows[604] = {"id": 604, "name": "even"}
    assert request(client, method, query)["items"] == [{"id": i} for i in rows if i % 2 == 0]
    assert len(calls["search"]) == 2
    assert calls["hydrate"] == []


@pytest.mark.parametrize("query", [
    {"select": "id,name"},
    {"select": "id", "where": ['name=="even"']},
    {},
])
def test_other_fields_still_load_records(source, query):
    client, rows, calls = source
    page = request(client, "GET", {"search": "even", **query})
    assert len(page["items"]) == 301
    assert calls["hydrate"]


def test_requested_ids_are_not_treated_as_existing_ids(source):
    client, rows, calls = source
    page = request(client, "GET", {"select": "id", "where": ["id in [2,999999]"]})
    assert page["items"] == [2]
    assert calls["hydrate"]


def test_opt_in_does_not_affect_other_search_adapters():
    from tsunagi.shared.planning import make_plan

    # A non-opted-in source may deliberately reject some candidate IDs.
    spec = SearchSpec(find_ids=lambda query: [1, 2], hydrate=lambda ids, wants: [{"id": 1}])
    plan = make_plan("id", None, SourceCaps(search=spec), "")
    assert plan.hydrate(plan.find_ids(), {"id"}) == [{"id": 1}]


def test_native_note_ids_do_not_reload_notes(tmp_path, monkeypatch):
    from tools.compat_bench.runtime import collection
    from tsunagi.http.v1.notes import router

    with collection(tmp_path / "collection.anki2") as col:
        model = col.models.by_name("Basic")
        expected = []
        for i in range(7):
            note = col.new_note(model)
            note.fields = [f"ID projection {i}", "back"]
            col.add_note(note, 1)
            expected.append(note.id)

        loaded = []
        original = col.get_note

        def tracked(nid):
            loaded.append(nid)
            return original(nid)

        monkeypatch.setattr(col, "get_note", tracked)
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.get("/v1/notes", params={"search": "", "select": "id"})
            assert response.status_code == 200, response.text
            assert response.json()["items"] == sorted(expected)
            assert loaded == []
            response = client.get("/v1/notes", params={"search": "", "select": "id,fields"})
            assert response.status_code == 200, response.text
            assert [item["id"] for item in response.json()["items"]] == sorted(expected)
            assert sorted(loaded) == sorted(expected)
