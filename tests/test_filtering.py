import pytest

from tsunagi.shared.filtering import (
    Clause,
    WhereParseError,
    build_predicate,
    parse_where,
)


class TestParseWhere:
    def test_equality_int(self):
        c = parse_where("id==123")
        assert c == Clause(tokens=("id",), op="==", value=123)

    def test_equality_quoted_string(self):
        c = parse_where('name=="Basic"')
        assert c.value == "Basic"

    def test_bare_identifier_is_string(self):
        c = parse_where("name==Basic")
        assert c.value == "Basic"

    def test_float_and_bool_and_null(self):
        assert parse_where("factor==2.5").value == 2.5
        assert parse_where("dyn==true").value is True
        assert parse_where("dyn==false").value is False
        assert parse_where("odid==null").value is None

    def test_comparison_ops(self):
        for op in ("!=", "~=", ">=", "<=", ">", "<"):
            c = parse_where(f"type{op}1")
            assert c.op == op

    def test_in_list(self):
        c = parse_where("id in [1,2,3]")
        assert c.op == "in"
        assert c.value == [1, 2, 3]

    def test_not_in_list(self):
        c = parse_where('name not in ["Basic","Cloze"]')
        assert c.op == "not in"
        assert c.value == ["Basic", "Cloze"]

    def test_nested_array_path(self):
        c = parse_where('fields[].name=="Front"')
        assert c.tokens == ("fields", "[]", "name")

    def test_dotted_path(self):
        c = parse_where("config.sticky==true")
        assert c.tokens == ("config", "sticky")

    @pytest.mark.parametrize("bad", ["", "id==", "==5", "id inn [1]", "name~", "id in 1,2"])
    def test_malformed_raises(self, bad):
        with pytest.raises(WhereParseError):
            parse_where(bad)

    def test_parse_error_is_value_error(self):
        # route layer maps ValueError -> 400; the parse error must subclass it
        with pytest.raises(ValueError):
            parse_where("totally (broken")


class TestBuildPredicate:
    ROWS = [
        {"id": 1, "name": "Basic", "type": 0, "fields": [{"name": "Front"}, {"name": "Back"}]},
        {"id": 2, "name": "Cloze", "type": 1, "fields": [{"name": "Text"}]},
        {"id": 3, "name": "Basic (reversed)", "type": 0, "fields": []},
    ]

    def _filter(self, *clauses):
        pred = build_predicate(list(clauses))
        return [r["id"] for r in self.ROWS if pred(r)]

    def test_equality(self):
        assert self._filter("id==2") == [2]

    def test_and_semantics(self):
        assert self._filter("type==0", "name~=reversed") == [3]

    def test_substring_case_insensitive(self):
        assert self._filter("name~=basic") == [1, 3]

    def test_nested_array_access(self):
        assert self._filter("fields[].name==Front") == [1]

    def test_in_and_not_in(self):
        assert self._filter("id in [1,3]") == [1, 3]
        assert self._filter("name not in [Basic, Cloze]") == [3]

    def test_missing_path_fails_clause(self):
        assert self._filter("nonexistent==1") == []

    def test_bool_int_not_confused(self):
        rows = [{"id": 1, "flag": True}, {"id": 2, "flag": 1}]
        pred = build_predicate(["flag==true"])
        assert [r["id"] for r in rows if pred(r)] == [1]

    def test_cmp_same_type_only(self):
        # "3" (str) must not compare against int threshold
        rows = [{"id": 1, "v": 5}, {"id": 2, "v": "5"}]
        pred = build_predicate(["v>=5"])
        assert [r["id"] for r in rows if pred(r)] == [1]

    def test_neq_means_none_equal(self):
        # != over an array: NO element may equal the value
        assert self._filter("fields[].name!=Front") == [2]
