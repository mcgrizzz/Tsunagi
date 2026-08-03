from tsunagi.shared.planning import IndexSpec, SourceCaps, make_plan

ROWS = [{"id": 1, "name": "Basic"}, {"id": 2, "name": "Cloze"}]


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def make_caps(calls):
    def fetch_values(vals):
        calls.append(list(vals))
        return [r for r in ROWS if r["id"] in vals]

    return SourceCaps(
        fetch_all=lambda: list(ROWS),
        indices=[IndexSpec(path=("id",), fetch_values=fetch_values, coerce=_int_or_none)],
        columns_fetchers={frozenset({"id", "name"}): lambda: [dict(r) for r in ROWS]},
    )


class TestIndexTier:
    def test_eq_uses_index(self):
        calls = []
        plan = make_plan(None, ["id==1"], make_caps(calls))
        assert plan.mode == "index"
        plan.fetch()
        assert calls == [[1]]

    def test_fetch_receives_coerced_deduped_values(self):
        # Regression (P1): the index fetcher must receive the coerced+deduped
        # values, not the raw parsed ones.
        calls = []
        plan = make_plan(None, ['id in ["1", 1, 2, "abc"]'], make_caps(calls))
        assert plan.mode == "index"
        plan.fetch()
        assert calls == [[1, 2]]

    def test_all_invalid_values_fall_through(self):
        calls = []
        plan = make_plan(None, ['id in ["abc", "def"]'], make_caps(calls))
        assert plan.mode == "full"
        assert calls == []

    def test_non_index_op_falls_through(self):
        plan = make_plan(None, ["id>=1"], make_caps([]))
        assert plan.mode == "full"

    def test_non_index_path_falls_through(self):
        plan = make_plan(None, ["name==Basic"], make_caps([]))
        assert plan.mode == "full"


class TestColumnsTier:
    def test_subset_select_uses_columns(self):
        plan = make_plan("id,name", None, make_caps([]))
        assert plan.mode == "columns"

    def test_smaller_subset_still_matches(self):
        plan = make_plan("id", None, make_caps([]))
        assert plan.mode == "columns"

    def test_array_select_falls_through(self):
        plan = make_plan("id,fields[].name", None, make_caps([]))
        assert plan.mode == "full"

    def test_unknown_field_falls_through(self):
        plan = make_plan("id,css", None, make_caps([]))
        assert plan.mode == "full"

    def test_where_needing_uncovered_field_falls_through(self):
        # Regression: select=id,name picked the columns fetcher even when the
        # where clause needed a field (fields[].name) the columns rows lack,
        # so the predicate silently matched nothing.
        plan = make_plan("id,name", ["fields[].name==Front"], make_caps([]))
        assert plan.mode == "full"

    def test_where_on_covered_field_keeps_columns(self):
        plan = make_plan("id,name", ["name~=Basic"], make_caps([]))
        assert plan.mode == "columns"


class TestFullTier:
    def test_no_hints_full_scan(self):
        plan = make_plan(None, None, make_caps([]))
        assert plan.mode == "full"
        assert plan.fetch() == ROWS

    def test_index_beats_columns(self):
        # where on an indexed path wins even when select could use columns
        calls = []
        plan = make_plan("id,name", ["id==2"], make_caps(calls))
        assert plan.mode == "index"
