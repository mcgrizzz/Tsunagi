from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

import pytest
from pydantic import BaseModel, Field, PrivateAttr, SecretStr

from tsunagi.shared.model_export import model_row_dict
from tsunagi.shared.route_factory import _as_dict, _plain
from tsunagi.shared.schemas.cards import CardInfo


class Child(BaseModel):
    name: str = Field(alias="wireName")


class Row(BaseModel):
    id: int
    data: Any


class Masked(BaseModel):
    visible: str = "shown"
    hidden: str = Field(default="secret", exclude=True)


class Included(BaseModel):
    visible: str = Field(default="shown", include=True)
    hidden: str = "secret"


class Root(BaseModel):
    __root__: list[int]


class Custom(BaseModel):
    id: int = 1

    def dict(self, **kwargs):
        return {"custom": self.id, "include_supplied": "include" in kwargs}


class Name(str, Enum):
    FRONT = "Front"


@pytest.mark.parametrize("data", [
    None, True, 2**60, 1.25, "犬 İ ΟΣ", [1, None, "Front"],
    {"fields": [Child(wireName="Front")], "_sa_keep_until_encoding": 3},
    datetime(2026, 9, 12, tzinfo=timezone.utc), Decimal("1.25"),
    (1, 2), {1, 2}, {1: "integer key"}, Name.FRONT, SecretStr("secret"),
    Masked(), Included(), Root(__root__=[1, 2]), Custom(),
])
@pytest.mark.parametrize("include", [None, {"id", "data"}, {"data": True}, set(), {"absent": True}])
def test_export_matches_pydantic(data, include):
    row = Row(id=1, data=data)
    assert model_row_dict(row, include=include) == row.dict(include=include)
    assert model_row_dict(row) == row.dict()


@pytest.mark.parametrize("row", [Masked(), Included(), Root(__root__=[1, 2]), Custom()])
def test_special_root_models_keep_their_export_rules(row):
    assert _plain(row) == row.dict()
    assert _as_dict(row) == row.dict(include=None)


@pytest.mark.parametrize("include", [
    {"data": {"items": {"__all__": {"name"}}}},
    {"data": {"items": {-1: {"name"}}}},
    {"data": ...},
])
def test_nested_selection_keeps_pydantic_behavior(include):
    row = Row(id=1, data={"items": [Child(wireName="Front"), Child(wireName="Back")]})
    assert model_row_dict(row, include=include) == row.dict(include=include)


def test_exports_read_live_values_and_do_not_share_mutable_containers():
    row = CardInfo(id=1, nid=2, did=3, fields=[{"name": "Front", "value": "before", "ord": 0}])
    exported = _as_dict(row, {"id", "note_id", "fields"})
    assert exported == row.dict(include={"id", "note_id", "fields"})
    assert "nid" not in exported
    exported["fields"][0]["value"] = "client edit"
    assert row.fields[0].value == "before"
    row.fields[0].value = "after"
    assert _plain(row)["fields"][0]["value"] == "after"
    assert _as_dict(row, {"fields"})["fields"][0]["value"] == "after"


def test_extra_fields_and_private_attributes():
    class Extra(Row):
        _private = PrivateAttr(default="hidden")

        class Config:
            extra = "allow"

    row = Extra(id=1, data={}, extra=[1, 2])
    assert model_row_dict(row) == row.dict() == {"id": 1, "data": {}, "extra": [1, 2]}


def test_nested_extra_root_key_keeps_pydantic_unwrapping():
    class Extra(BaseModel):
        id: int = 1

        class Config:
            extra = "allow"

    row = Row(id=2, data=Extra(__root__=[1, 2]))
    assert model_row_dict(row) == row.dict() == {"id": 2, "data": [1, 2]}


def test_overridden_value_conversion_uses_pydantic():
    class Converted(Row):
        @classmethod
        def _get_value(cls, value, *args, **kwargs):
            if isinstance(value, str):
                return "custom: " + value
            return super()._get_value(value, *args, **kwargs)

    row = Converted(id=1, data="Front")
    assert model_row_dict(row) == row.dict() == {"id": 1, "data": "custom: Front"}


def test_overridden_iteration_uses_pydantic():
    class Iterated(Row):
        def _iter(self, *args, **kwargs):
            yield "export_mode", kwargs.get("to_dict")

    row = Iterated(id=1, data="Front")
    assert model_row_dict(row) == row.dict() == {"export_mode": True}


def test_overridden_key_selection_uses_pydantic():
    class Keys(Row):
        def _calculate_keys(self, include, exclude, exclude_unset, update=None):
            if include is None:
                return {"id"}
            return super()._calculate_keys(include, exclude, exclude_unset, update)

    row = Keys(id=1, data="Front")
    assert model_row_dict(row) == row.dict() == {"id": 1}
    assert model_row_dict(row, include={"data"}) == row.dict(include={"data"}) == {"data": "Front"}
