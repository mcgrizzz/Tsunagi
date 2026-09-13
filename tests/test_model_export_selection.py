"""Nested selections retain Pydantic's masks, aliases and fallback behavior."""
from typing import Any

import pytest
from pydantic import BaseModel, Field

from tsunagi.shared.model_export import model_row_dict


class FieldRow(BaseModel):
    name: str = Field(alias="wireName")
    ord: int = 0


class Row(BaseModel):
    id: int = 1
    fields: Any


def assert_matches_pydantic(row, include):
    try:
        expected = row.dict(include=include)
    except (TypeError, ValueError) as exc:
        with pytest.raises(type(exc)) as actual:
            model_row_dict(row, include=include)
        assert str(actual.value) == str(exc)
    else:
        assert model_row_dict(row, include=include) == expected


@pytest.mark.parametrize("fields", [
    [], [FieldRow(wireName="Front"), FieldRow(wireName="Back", ord=1)],
    [{"name": "Front", "ord": 0}], [{"missing": True}],
    [None, "text", {"name": "犬 İ ΟΣ"}], None,
    [[{"name": "Front"}]], {"child": FieldRow(wireName="Front")},
])
@pytest.mark.parametrize("mask", [
    {"__all__": {"name"}},
    {"__all__": {"name": True}},
    {"__all__": {"name": True, "ord": True}},
    {"__all__": {"wireName": True}},
    {"__all__": {"__all__": {"name": True}}},
    {"child": {"name": True}},
])
def test_nested_selections_match_pydantic(fields, mask):
    row = Row(fields=fields)
    include = {"id": True, "fields": mask}
    assert_matches_pydantic(row, include)


@pytest.mark.parametrize("mask", [
    {}, set(), {"__all__": {}}, {"__all__": set()},
    {"__all__": {"name": None}}, {"__all__": {"name": False}},
    {"__all__": {"name"}}, {-1: {"name"}},
    {"__all__": {"name": True}, 0: {"ord": True}},
    {"__all__": 1}, {"__all__": "name"},
])
@pytest.mark.parametrize("fields", [[], [FieldRow(wireName="Front")],
                                    [{"name": "Front", "ord": 0}]])
def test_unusual_masks_keep_results_and_errors(fields, mask):
    row = Row(fields=fields)
    include = {"fields": mask}
    assert_matches_pydantic(row, include)


def test_nested_selection_keeps_exclusions_and_reads_current_values():
    class HiddenField(FieldRow):
        ord: int = Field(default=0, exclude=True)

    row = Row(fields=[HiddenField(wireName="Front")])
    include = {"fields": {"__all__": {"name": True, "ord": True}}}
    first = model_row_dict(row, include=include)
    assert first == {"fields": [{"name": "Front"}]}
    row.fields[0].name = "Changed"
    second = model_row_dict(row, include=include)
    assert second == {"fields": [{"name": "Changed"}]}
    assert first == {"fields": [{"name": "Front"}]}
