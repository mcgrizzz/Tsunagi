import pytest

from tsunagi.shared.selecting import (
    SelectArrayMulti,
    SelectArrayPluck,
    SelectParseError,
    SelectScalar,
    SelectValidationError,
    maybe_flatten,
    parse_select_csv,
    project_scalars,
    selected_top_fields,
)

OBJ = {
    "id": 1,
    "name": "Basic",
    "fields": [
        {"name": "Front", "ord": 0, "font": "Arial"},
        {"name": "Back", "ord": 1, "font": "Arial"},
    ],
}


class TestParseSelect:
    def test_scalars(self):
        nodes = parse_select_csv("id,name")
        assert nodes == [SelectScalar(path=("id",)), SelectScalar(path=("name",))]

    def test_scalar_alias(self):
        assert parse_select_csv("name:displayName") == [
            SelectScalar(path=("name",), as_name="displayName")
        ]

    def test_array_copy_and_child(self):
        assert parse_select_csv("fields[]") == [SelectArrayPluck(base=("fields",))]
        assert parse_select_csv("fields[].name:labels") == [
            SelectArrayPluck(base=("fields",), child=("name",), as_name="labels")
        ]

    def test_array_multi_with_aliases(self):
        nodes = parse_select_csv("fields[].(name:nm,ord:ix):flds")
        assert nodes == [
            SelectArrayMulti(
                base=("fields",),
                children=((("name",), "nm"), (("ord",), "ix")),
                as_name="flds",
            )
        ]

    def test_empty_returns_no_nodes(self):
        assert parse_select_csv("") == []

    @pytest.mark.parametrize("bad", ["fields[", "id,,name", "fields[].(name", "1abc"])
    def test_malformed_raises(self, bad):
        with pytest.raises(SelectParseError):
            parse_select_csv(bad)


class TestProjectScalars:
    def test_no_nodes_copies(self):
        assert project_scalars(OBJ, []) == OBJ

    def test_scalar_projection(self):
        nodes = parse_select_csv("id,name")
        assert project_scalars(OBJ, nodes) == {"id": 1, "name": "Basic"}

    def test_missing_scalar_is_none(self):
        nodes = parse_select_csv("id,missing")
        assert project_scalars(OBJ, nodes) == {"id": 1, "missing": None}

    def test_top_level_aliases_keep_composite_values_and_last_alias(self):
        row = {"id": 7, "name": "食べる", "fields": [{"name": "Front", "value": "食べる"}],
               "metadata": {"language": "ja"}, "optional": None}
        nodes = parse_select_csv("fields:content,metadata,optional,id:key,missing:key,name:label")
        assert project_scalars(row, nodes) == {
            "content": row["fields"], "metadata": {"language": "ja"}, "optional": None,
            "key": None, "label": "食べる",
        }

    def test_same_projection_reads_current_row_values(self):
        row = {"name": "before", "fields": []}
        nodes = parse_select_csv("name,fields")
        assert project_scalars(row, nodes) == {"name": "before", "fields": []}
        row.update(name="after", fields=[{"name": "New field"}])
        assert project_scalars(row, nodes) == {"name": "after", "fields": [{"name": "New field"}]}
        assert project_scalars({}, nodes) == {"name": None, "fields": None}

    def test_array_child_pluck(self):
        nodes = parse_select_csv("fields[].name")
        assert project_scalars(OBJ, nodes) == {"fields": ["Front", "Back"]}

    def test_missing_array_is_empty(self):
        nodes = parse_select_csv("templates[].name")
        assert project_scalars(OBJ, nodes) == {"templates": []}

    def test_multi_pluck_aliases(self):
        nodes = parse_select_csv("fields[].(name:nm,ord:ix)")
        assert project_scalars(OBJ, nodes) == {
            "fields": [{"nm": "Front", "ix": 0}, {"nm": "Back", "ix": 1}]
        }


class TestUnicodeNames:
    def test_unicode_field_name(self):
        nodes = parse_select_csv("単語")
        assert project_scalars({"単語": "犬"}, nodes) == {"単語": "犬"}

    def test_unicode_array_pluck(self):
        nodes = parse_select_csv("フィールド[].名前")
        assert project_scalars({"フィールド": [{"名前": "表"}]}, nodes) == {"フィールド": ["表"]}


class TestMaybeFlatten:
    def test_auto_flattens_single_scalar_field(self):
        nodes = parse_select_csv("name")
        rows = [{"name": "Basic"}, {"name": "Cloze"}]
        assert maybe_flatten(rows, nodes, "auto") == ["Basic", "Cloze"]

    def test_object_shape_never_flattens(self):
        nodes = parse_select_csv("name")
        rows = [{"name": "Basic"}]
        assert maybe_flatten(rows, nodes, "object") == rows

    def test_auto_keeps_objects_for_multiple_fields(self):
        nodes = parse_select_csv("id,name")
        rows = [{"id": 1, "name": "Basic"}]
        assert maybe_flatten(rows, nodes, "auto") == rows

    def test_scalar_shape_requires_single_field(self):
        nodes = parse_select_csv("id,name")
        with pytest.raises(SelectValidationError):
            maybe_flatten([{"id": 1, "name": "x"}], nodes, "scalar")

    def test_scalar_shape_requires_scalar_values(self):
        nodes = parse_select_csv("fields[]")
        rows = [{"fields": [{"name": "Front"}]}]
        with pytest.raises(SelectValidationError):
            maybe_flatten(rows, nodes, "scalar")

    def test_scalar_shape_returns_values(self):
        nodes = parse_select_csv("id")
        assert maybe_flatten([{"id": 1}, {"id": 2}], nodes, "scalar") == [1, 2]


class TestSelectedTopFields:
    def test_scalars_only(self):
        assert selected_top_fields("id,name") == {"id", "name"}

    def test_arrays_disqualify(self):
        assert selected_top_fields("id,fields[].name") is None

    def test_empty(self):
        assert selected_top_fields(None) is None
        assert selected_top_fields("") is None
