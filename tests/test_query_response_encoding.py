"""The query shortcut must preserve FastAPI's response contract."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from tsunagi.shared import route_factory
from tsunagi.shared.route_factory import ModelRow
from tsunagi.shared.schemas.wrappers import Paginated


class NamedRow(BaseModel):
    name: str = Field(alias="wireName")


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_query_encoding_matches_framework(method, monkeypatch):
    page = Paginated[ModelRow](items=[{
        "id": 1, "unicode": "食べる", "missing": None, "flag": False,
        "date": datetime(2026, 9, 12, tzinfo=timezone.utc), "decimal": Decimal("1.25"),
        "uuid": UUID(int=1), "bytes": b"abc", "tuple": (1, 2),
        "nested": {"row": NamedRow(wireName="Front"), "_sa_hidden": "hidden"},
    }], next_cursor="cursor", stats={"duration_ms": 1.25})
    monkeypatch.setattr(route_factory, "_execute_query", lambda **kwargs: page)
    app = FastAPI()
    app.include_router(route_factory.create_resource_routes(
        "/query", caps=SimpleNamespace(mutations=None), response_model=Paginated[ModelRow],
        resource_name="item", resource_plural="items", tag="Test",
    ))

    @app.get("/reference", response_model=Paginated[ModelRow], response_model_by_alias=False)
    def reference():
        return page

    with TestClient(app) as client:
        expected = client.get("/reference")
        actual = client.get("/query") if method == "GET" else client.post("/query/query", json={})
    assert actual.status_code == expected.status_code == 200
    assert actual.json() == expected.json()
    assert actual.headers["content-type"] == expected.headers["content-type"]


def test_custom_query_response_still_validates(monkeypatch):
    class StrictPage(BaseModel):
        items: list[int]

    page = Paginated[ModelRow](items=["invalid"], next_cursor=None, stats={})
    monkeypatch.setattr(route_factory, "_execute_query", lambda **kwargs: page)
    app = FastAPI()
    app.include_router(route_factory.create_resource_routes(
        "/query", caps=SimpleNamespace(mutations=None), response_model=StrictPage,
        resource_name="item", resource_plural="items", tag="Test",
    ))
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/query").status_code == 500


def test_narrow_projection_keeps_validation_and_human_field_names():
    from tsunagi.shared.schemas.models import ModelInfo

    raw = {"id": 1, "name": "Basic", "sortf": 1, "tmpls": [],
           "flds": [{"name": " Front ", "ord": 0, "plainText": True}]}
    row = ModelInfo.parse_obj(raw)
    page = route_factory._finish([row], None, "sort_field,fields[].(name,plain_text)", "object", 0)
    assert page.items == [{"sort_field": 1, "fields": [{"name": "Front", "plain_text": True}]}]
    assert route_factory._as_dict(row, {"fields"}) == {"fields": row.dict()["fields"]}


@pytest.mark.parametrize("select", [
    "fields[].name", "fields[].name,fields[].ord", "fields[].(name,plain_text)",
    "fields[],fields[].name:names", "fields[].name:names,fields[]", "fields,fields[].ord:ords",
    "name,fields[].missing,templates[].qfmt", "fields[].name:same,name:same",
])
def test_partial_model_conversion_matches_full_conversion(select):
    from tsunagi.shared.schemas.models import ModelInfo
    from tsunagi.shared.selecting import (
        parse_select_csv,
        project_scalars,
        selection_include,
    )

    row = ModelInfo.parse_obj({"id": 1, "name": "Basic", "tmpls": [{"name": "Card", "ord": 0}],
                               "flds": [{"name": "Front", "ord": 0, "plainText": True}]})
    nodes = parse_select_csv(select)
    actual = project_scalars(row.dict(include=selection_include(nodes)), nodes)
    expected = project_scalars(row.dict(), nodes)
    assert actual == expected


@pytest.mark.parametrize("values", [None, 0, False, "text", {}, {"name": "Front"},
                                    [None], [(1, "value")], ({"name": "Front"},),
                                    [{"name": "Front"}], [NamedRow(wireName="Front")]])
def test_partial_conversion_preserves_irregular_array_values(values):
    from tsunagi.shared.selecting import (
        parse_select_csv,
        project_scalars,
        selection_include,
    )

    class Row(BaseModel):
        fields: Any

    row = Row(fields=values)
    nodes = parse_select_csv("fields[].name")
    actual = project_scalars(route_factory._as_dict(row, selection_include(nodes)), nodes)
    assert actual == project_scalars(row.dict(), nodes)
