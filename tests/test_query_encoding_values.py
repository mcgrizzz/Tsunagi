"""Compare the JSON shortcut with the framework, including whole-page fallbacks."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, IntEnum

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tsunagi.shared import query_encoding
from tsunagi.shared.route_factory import ModelRow
from tsunagi.shared.schemas.wrappers import Paginated


class Name(Enum):
    FRONT = "Front"


class Number(IntEnum):
    ONE = 1


@dataclass
class Value:
    name: str


class CustomRow(BaseModel):
    date: datetime = Field(alias="wireDate")

    class Config:
        json_encoders = {datetime: lambda value: "custom date"}


@pytest.mark.parametrize("value", [
    {"unicode": "食べる", "numbers": [0, -1, 1.5, 2**60], "bools": [True, False, None],
     "nested": [{"_sa_hidden": 3, "visible": []}], "_sa_root": 4},
    {"text": '"_sa is text, not a key', "number": 2**60},
    {"enum": Name.FRONT, "integer_enum": Number.ONE},
    {1: "number key", None: "none key", Name.FRONT: "enum key"},
    {"dataclass": Value("Front"), "tuple": (1, 2), "set": {1, 2}},
    {"model": CustomRow(wireDate=datetime(2026, 9, 12, tzinfo=timezone.utc))},
])
def test_encoded_values_match_framework_without_changing_page(value):
    page = Paginated[ModelRow](items=[value], next_cursor=None, stats={"duration_ms": 0})
    expected = JSONResponse(jsonable_encoder(page, by_alias=True)).body
    assert query_encoding.render_query_page(page) == expected
    assert JSONResponse(jsonable_encoder(page, by_alias=True)).body == expected


def test_plain_page_does_not_use_framework_conversion(monkeypatch):
    page = Paginated[ModelRow](items=[{"id": 1, "fields": [{"name": "Front", "value": "word"}]}],
                               next_cursor=None, stats={"duration_ms": 0})
    expected = jsonable_encoder(page)
    def unexpected(*args, **kwargs):
        pytest.fail("A plain JSON page should not be recursively converted again")
    monkeypatch.setattr(query_encoding, "jsonable_encoder", unexpected)
    monkeypatch.setattr(type(page), "dict", unexpected)
    assert query_encoding.render_query_page(page) == JSONResponse(expected).body


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_numbers_still_fail_json_serialization(value):
    page = Paginated[ModelRow](items=[{"value": value}], next_cursor=None, stats={})
    with pytest.raises(ValueError):
        JSONResponse(jsonable_encoder(page))
    with pytest.raises(ValueError):
        query_encoding.render_query_page(page)
