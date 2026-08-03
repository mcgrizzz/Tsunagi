"""
Route-factory tests over an in-memory fake resource - no Anki involved.

Exercises the whole HTTP pipeline: planner, where-DSL, select projection,
keyset pagination, mutations, and subresource CRUD.
"""
import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tsunagi.shared.errors import (
    AnkiBusyError,
    CollectionUnavailableError,
    ResourceNotFoundError,
    register_exception_handlers,
)
from tsunagi.shared.errors import ValidationError as TsunagiValidationError
from tsunagi.shared.planning import (
    IndexSpec,
    MutationCaps,
    SearchSpec,
    SourceCaps,
    SubresourceMutations,
)
from tsunagi.shared.route_factory import create_resource_routes, make_id_getter

SEED = [
    {"id": 1, "name": "Basic", "type": 0, "fields": [{"name": "Front", "ord": 0}, {"name": "Back", "ord": 1}]},
    {"id": 2, "name": "Cloze", "type": 1, "fields": [{"name": "Text", "ord": 0}]},
    {"id": 3, "name": "Basic (typed)", "type": 0, "fields": [{"name": "Front", "ord": 0}]},
]


class FakeStore:
    def __init__(self):
        self.rows = copy.deepcopy(SEED)

    def _get(self, rid):
        for r in self.rows:
            if r["id"] == rid:
                return r
        return None

    # --- queries ---
    def fetch_all(self):
        return copy.deepcopy(self.rows)

    def fetch_by_ids(self, ids, wants=None):
        return [copy.deepcopy(r) for r in self.rows if r["id"] in set(ids)]

    def fetch_id_name(self):
        return [{"id": r["id"], "name": r["name"]} for r in self.rows]

    # --- mutations ---
    def create(self, data):
        new = {"id": max((r["id"] for r in self.rows), default=0) + 1,
               "name": data["name"], "type": data.get("type", 0), "fields": []}
        self.rows.append(new)
        return copy.deepcopy(new)

    def patch(self, rid, updates):
        row = self._get(rid)
        if row is None:
            raise ResourceNotFoundError("model", rid)
        row.update({k: v for k, v in updates.items() if k in ("name", "type")})
        return copy.deepcopy(row)

    def delete(self, rid):
        row = self._get(rid)
        if row is None:
            return False
        self.rows.remove(row)
        return True

    # --- subresource (fields) ---
    def _parent(self, rid):
        row = self._get(rid)
        if row is None:
            raise ResourceNotFoundError("model", rid)
        return row

    def field_create(self, rid, data):
        row = self._parent(rid)
        row["fields"].append({"name": data["name"], "ord": len(row["fields"])})
        return copy.deepcopy(row)

    def field_patch(self, rid, name, updates):
        row = self._parent(rid)
        for f in row["fields"]:
            if f["name"] == name:
                f.update(updates)
                return copy.deepcopy(row)
        raise TsunagiValidationError(f"field '{name}' not found")

    def field_delete(self, rid, name):
        row = self._parent(rid)
        row["fields"] = [f for f in row["fields"] if f["name"] != name]
        return copy.deepcopy(row)

    def field_reorder(self, rid, order):
        row = self._parent(rid)
        by_name = {f["name"]: f for f in row["fields"]}
        if set(order) != set(by_name):
            raise TsunagiValidationError("order mismatch")
        row["fields"] = [by_name[n] for n in order]
        return copy.deepcopy(row)


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@pytest.fixture()
def store():
    return FakeStore()


@pytest.fixture()
def client(store):
    caps = SourceCaps(
        fetch_all=store.fetch_all,
        indices=[IndexSpec(path=("id",), fetch_values=store.fetch_by_ids, coerce=_int_or_none)],
        columns_fetchers={frozenset({"id", "name"}): store.fetch_id_name},
        mutations=MutationCaps(
            create=store.create,
            patch=store.patch,
            delete=store.delete,
            subresources={
                "fields": SubresourceMutations(
                    json_key="fields",
                    id_field="name",
                    create=store.field_create,
                    patch=store.field_patch,
                    delete=store.field_delete,
                    reorder=store.field_reorder,
                ),
            },
        ),
    )
    app = FastAPI()
    app.include_router(create_resource_routes(
        path="/v1/things",
        caps=caps,
        response_model=None,
        id_getter=make_id_getter("id"),
        resource_name="thing",
        resource_plural="things",
        tag="Things",
    ))
    return TestClient(app)


class TestQueries:
    def test_list_all(self, client):
        body = client.get("/v1/things").json()
        assert [r["id"] for r in body["items"]] == [1, 2, 3]
        assert body["next_cursor"] is None
        assert "duration_ms" in body["stats"]

    def test_where_filter(self, client):
        body = client.get("/v1/things", params={"where": "type==0"}).json()
        assert [r["id"] for r in body["items"]] == [1, 3]

    def test_where_on_index_still_post_filters(self, client):
        body = client.get("/v1/things", params=[("where", "id in [1,2]"), ("where", "type==1")]).json()
        assert [r["id"] for r in body["items"]] == [2]

    def test_select_projection(self, client):
        body = client.get("/v1/things", params={"select": "id,name", "shape": "object"}).json()
        assert body["items"][0] == {"id": 1, "name": "Basic"}

    def test_select_single_field_auto_flattens(self, client):
        body = client.get("/v1/things", params={"select": "name"}).json()
        assert body["items"] == ["Basic", "Cloze", "Basic (typed)"]

    def test_nested_select(self, client):
        body = client.get("/v1/things", params={"select": "fields[].name", "where": "id==1", "shape": "object"}).json()
        assert body["items"] == [{"fields": ["Front", "Back"]}]

    def test_pagination_flow(self, client):
        p1 = client.get("/v1/things", params={"limit": 2}).json()
        assert [r["id"] for r in p1["items"]] == [1, 2]
        p2 = client.get("/v1/things", params={"limit": 2, "cursor": p1["next_cursor"]}).json()
        assert [r["id"] for r in p2["items"]] == [3]
        assert p2["next_cursor"] is None

    def test_post_query_parity(self, client):
        get_body = client.get("/v1/things", params={"select": "id,name", "where": "type==0", "shape": "object"}).json()
        post_body = client.post("/v1/things/query", json={"select": "id,name", "where": ["type==0"], "shape": "object"}).json()
        assert get_body["items"] == post_body["items"]

    def test_malformed_where_is_400(self, client):
        resp = client.get("/v1/things", params={"where": "totally (broken"})
        assert resp.status_code == 400

    def test_malformed_select_is_400(self, client):
        resp = client.get("/v1/things", params={"where": "id==1", "select": "fields["})
        assert resp.status_code == 400

    def test_nested_where_with_columns_covered_select(self, client):
        # Regression: this combination hit the {id,name} columns fetcher whose
        # rows lack "fields", so the filter returned [] despite matches.
        body = client.get("/v1/things", params={
            "select": "id,name", "where": "fields[].name==Front", "shape": "object",
        }).json()
        assert [r["id"] for r in body["items"]] == [1, 3]

    def test_row_without_id_is_400_not_500(self, store, client):
        # Regression (P2): HTTPException(400) from make_id_getter must not be
        # swallowed into a 500 by the generic handler.
        store.rows.append({"name": "orphan"})
        resp = client.get("/v1/things")
        assert resp.status_code == 400

    def test_internal_error_hides_detail(self):
        caps = SourceCaps(fetch_all=lambda: (_ for _ in ()).throw(RuntimeError("secret internals")))
        app = FastAPI()
        app.include_router(create_resource_routes(
            path="/v1/boom", caps=caps, response_model=None,
            resource_name="boom", resource_plural="booms", tag="Boom",
        ))
        resp = TestClient(app, raise_server_exceptions=False).get("/v1/boom")
        assert resp.status_code == 500
        assert "secret internals" not in resp.text


class TestSearchParam:
    """The search tier over the HTTP surface, incl. GET/POST parity."""

    @pytest.fixture()
    def search_client(self, store):
        def find_ids(query):
            # Trivial stand-in for Anki search: "type0" -> the type==0 rows
            rows = store.rows if query != "type0" else [r for r in store.rows if r["type"] == 0]
            return [r["id"] for r in rows]

        caps = SourceCaps(
            indices=[IndexSpec(path=("id",), fetch_values=store.fetch_by_ids, coerce=_int_or_none)],
            search=SearchSpec(find_ids=find_ids, hydrate=store.fetch_by_ids),
        )
        app = FastAPI()
        app.include_router(create_resource_routes(
            path="/v1/things", caps=caps, response_model=None,
            id_getter=make_id_getter("id"),
            resource_name="thing", resource_plural="things", tag="Things",
        ))
        return TestClient(app)

    def test_search_filters(self, search_client):
        body = search_client.get("/v1/things", params={"search": "type0"}).json()
        assert [r["id"] for r in body["items"]] == [1, 3]

    def test_bare_list_uses_scan(self, search_client):
        # No fetch_all on these caps: a plain GET still works via the scan tier
        body = search_client.get("/v1/things").json()
        assert [r["id"] for r in body["items"]] == [1, 2, 3]

    def test_get_post_parity(self, search_client):
        get_body = search_client.get(
            "/v1/things", params={"search": "type0", "select": "id,name", "shape": "object"}
        ).json()
        post_body = search_client.post(
            "/v1/things/query",
            json={"search": "type0", "select": "id,name", "shape": "object"},
        ).json()
        assert get_body["items"] == post_body["items"]

    def test_unsupported_search_is_400(self, client):
        # `client` fixture has no SearchSpec
        assert client.get("/v1/things", params={"search": "x"}).status_code == 400

    def test_short_page_still_has_cursor(self, search_client):
        # Documented contract: on search-backed resources `where` filters the
        # page AFTER id-level pagination, so a page can be empty while more
        # pages remain. Clients must iterate until next_cursor is null.
        body = search_client.get(
            "/v1/things", params={"limit": 1, "where": "name==Cloze"}
        ).json()
        assert body["items"] == []
        assert body["next_cursor"] is not None

    def test_cursor_walks_every_row(self, search_client):
        seen, cursor = [], None
        while True:
            params = {"limit": 1}
            if cursor:
                params["cursor"] = cursor
            body = search_client.get("/v1/things", params=params).json()
            seen += [r["id"] for r in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert seen == [1, 2, 3]


class TestAvailabilityErrors:
    """M1 regression: Anki-busy / collection-closed surface as 503, not 500."""

    def _client(self, caps):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(create_resource_routes(
            path="/v1/things", caps=caps, response_model=None,
            resource_name="thing", resource_plural="things", tag="Things",
        ))
        return TestClient(app, raise_server_exceptions=False)

    def _raise(self, exc):
        def _f(*args, **kwargs):
            raise exc
        return _f

    def test_busy_read_is_503(self):
        client = self._client(SourceCaps(fetch_all=self._raise(AnkiBusyError())))
        resp = client.get("/v1/things")
        assert resp.status_code == 503
        assert "timed out" in resp.json()["detail"]

    def test_unavailable_read_is_503(self):
        client = self._client(SourceCaps(fetch_all=self._raise(CollectionUnavailableError())))
        assert client.get("/v1/things").status_code == 503

    def test_unavailable_mutation_is_503(self):
        caps = SourceCaps(
            fetch_all=lambda: [],
            mutations=MutationCaps(create=self._raise(CollectionUnavailableError())),
        )
        resp = self._client(caps).post("/v1/things", json={"name": "x"})
        assert resp.status_code == 503

    def test_busy_mutation_is_503(self):
        caps = SourceCaps(
            fetch_all=lambda: [],
            mutations=MutationCaps(create=self._raise(AnkiBusyError())),
        )
        assert self._client(caps).post("/v1/things", json={"name": "x"}).status_code == 503


class TestMutations:
    def test_create(self, client):
        resp = client.post("/v1/things", json={"name": "New"})
        assert resp.status_code == 201
        assert resp.json()["result"]["name"] == "New"

    def test_patch(self, client):
        resp = client.patch("/v1/things/2", json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.json()["result"]["name"] == "Renamed"

    def test_patch_missing_is_404(self, client):
        assert client.patch("/v1/things/999", json={"name": "x"}).status_code == 404

    def test_delete(self, client):
        assert client.delete("/v1/things/3").json()["success"] is True

    def test_delete_missing_is_404(self, client):
        assert client.delete("/v1/things/999").status_code == 404


class TestSubresources:
    def test_field_create(self, client):
        resp = client.post("/v1/things/2/fields", json={"name": "Extra"})
        assert resp.status_code == 201
        names = [f["name"] for f in resp.json()["result"]["fields"]]
        assert names == ["Text", "Extra"]

    def test_field_patch(self, client):
        resp = client.patch("/v1/things/1/fields/Front", json={"ord": 5})
        assert resp.json()["result"]["fields"][0]["ord"] == 5

    def test_field_patch_missing_is_400(self, client):
        assert client.patch("/v1/things/1/fields/Nope", json={"ord": 5}).status_code == 400

    def test_field_delete(self, client):
        resp = client.delete("/v1/things/1/fields/Back")
        names = [f["name"] for f in resp.json()["result"]["fields"]]
        assert names == ["Front"]

    def test_field_reorder(self, client):
        resp = client.put("/v1/things/1/fields:order", json={"order": ["Back", "Front"]})
        names = [f["name"] for f in resp.json()["result"]["fields"]]
        assert names == ["Back", "Front"]

    def test_reorder_requires_order(self, client):
        assert client.put("/v1/things/1/fields:order", json={}).status_code == 400

    def test_missing_parent_is_404(self, client):
        assert client.post("/v1/things/999/fields", json={"name": "X"}).status_code == 404
