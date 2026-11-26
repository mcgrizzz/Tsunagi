"""Check optimized selections against the existing glom semantics."""
import pytest
from glom import glom

from tsunagi.shared.selecting import _build_spec, parse_select_csv, project_scalars


@pytest.mark.parametrize("select", [
    "id,fields[]", "id,fields[].name", "fields[].(name,ord)",
    "fields[],fields[].name", "fields[].name,fields[]", "fields[].(name,ord,name)", "fields[].読み",
    "missing[].name,id,fields[].missing",
    'fields[name in ["Front"]]', 'fields[name in ["Front","Back"]].ord',
    'fields[ord in [0]].(name,ord)', 'fields[name in [""]].name',
])
@pytest.mark.parametrize("values", [
    [], [{"name": "Front", "ord": 0, "読み": "よみ"}, {"name": "Back", "ord": 1}],
    [{}, {"name": None}, {"name": ""}], [{"nested": {"name": "Front"}}],
    None, 0, False, "text", {}, {"name": "Front"}, [None], [1, "text"],
    ({"name": "tuple"},), [{"name": [1, 2]}, {"name": {"nested": True}}],
])
def test_common_and_irregular_shapes_match_glom(select, values):
    obj = {"id": 1, "fields": values, "nested": {"fields": values}}
    nodes = parse_select_csv(select)
    assert project_scalars(obj, nodes) == glom(obj, _build_spec(tuple(nodes)), default=None)


def test_array_selection_reads_new_values_without_mutating_the_input():
    obj = {"fields": [{"name": "Front", "ord": 0}]}
    nodes = parse_select_csv("fields[].(name,ord)")
    first = project_scalars(obj, nodes)
    first["fields"][0]["name"] = "client edit"
    assert obj["fields"][0]["name"] == "Front"
    obj["fields"][0]["name"] = "Renamed"
    assert project_scalars(obj, nodes) == {"fields": [{"name": "Renamed", "ord": 0}]}


def test_rows_that_already_match_the_selection_are_not_copied():
    from tsunagi.shared.route_factory import _finish

    rows = [{"id": 1, "rating": 3}, {"id": 2, "rating": 4}]
    page = _finish(rows, None, "id,rating", None, 0.0)
    assert page.items is rows


def test_rows_with_other_keys_or_order_are_projected_in_the_selections_order():
    from tsunagi.shared.route_factory import _finish

    rows = [{"rating": 3, "id": 1, "type": 0}]
    page = _finish(rows, None, "id,rating", None, 0.0)
    assert page.items == [{"id": 1, "rating": 3}] and list(page.items[0]) == ["id", "rating"]
    assert rows == [{"rating": 3, "id": 1, "type": 0}]
