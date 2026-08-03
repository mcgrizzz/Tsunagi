import pytest

from tsunagi.shared.planning import IndexSpec, SearchSpec, SourceCaps, make_plan

ROWS = [{"id": 1, "name": "Basic"}, {"id": 2, "name": "Cloze"}]


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def make_caps(calls):
    def fetch_values(vals, wants=None):
        calls.append(list(vals))
        return [r for r in ROWS if r["id"] in vals]

    return SourceCaps(
        fetch_all=lambda wants=None: list(ROWS),
        indices=[IndexSpec(path=("id",), fetch_values=fetch_values, coerce=_int_or_none)],
        columns_fetchers={frozenset({"id", "name"}): lambda wants=None: [dict(r) for r in ROWS]},
    )


class TestIndexTier:
    def test_eq_uses_index(self):
        calls = []
        plan = make_plan(None, ["id==1"], make_caps(calls))
        assert plan.mode == "index"
        plan.fetch(None)
        assert calls == [[1]]

    def test_fetch_receives_coerced_deduped_values(self):
        # Regression (P1): the index fetcher must receive the coerced+deduped
        # values, not the raw parsed ones.
        calls = []
        plan = make_plan(None, ['id in ["1", 1, 2, "abc"]'], make_caps(calls))
        assert plan.mode == "index"
        plan.fetch(None)
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


class TestSearchTier:
    """Search-backed resources: ids are paged first, only the page hydrates."""

    def make_search_caps(self, log, with_fetch_all=False):
        def find_ids(query):
            log.append(("find", query))
            return [r["id"] for r in ROWS]

        def hydrate(ids, wants=None):
            log.append(("hydrate", list(ids), wants))
            return [r for r in ROWS if r["id"] in set(ids)]

        return SourceCaps(
            fetch_all=(lambda wants=None: list(ROWS)) if with_fetch_all else None,
            indices=[IndexSpec(path=("id",), fetch_values=hydrate, coerce=_int_or_none)],
            search=SearchSpec(find_ids=find_ids, hydrate=hydrate),
        )

    def test_search_uses_search_tier(self):
        log = []
        plan = make_plan(None, None, self.make_search_caps(log), "deck:JP")
        assert plan.mode == "search"
        plan.find_ids()
        assert log[0] == ("find", "deck:JP")

    def test_search_beats_index(self):
        # Correctness, not preference: the index tier can't evaluate 'deck:JP',
        # so letting it win would silently drop the search terms.
        plan = make_plan(None, ["id==1"], self.make_search_caps([]), "deck:JP")
        assert plan.mode == "search"

    def test_search_unsupported_is_error(self):
        caps = SourceCaps(fetch_all=lambda wants=None: list(ROWS))
        with pytest.raises(ValueError, match="search is not supported"):
            make_plan(None, None, caps, "deck:JP")

    def test_no_search_scans_when_no_fetch_all(self):
        log = []
        plan = make_plan(None, None, self.make_search_caps(log))
        assert plan.mode == "scan"
        plan.find_ids()
        assert log[0] == ("find", "")  # empty query = whole collection

    def test_fetch_all_wins_over_scan(self):
        plan = make_plan(None, None, self.make_search_caps([], with_fetch_all=True))
        assert plan.mode == "full"

    def test_hydrate_receives_wants(self):
        log = []
        caps = self.make_search_caps(log)
        plan = make_plan(None, None, caps, "x")
        plan.hydrate([1, 2], {"id", "name"})
        hydrate_call = [c for c in log if c[0] == "hydrate"][0]
        assert hydrate_call[1] == [1, 2]
        assert hydrate_call[2] == {"id", "name"}  # wants threaded through

    def test_no_enumeration_path_is_error(self):
        with pytest.raises(ValueError, match="no way to enumerate"):
            make_plan(None, None, SourceCaps())


class TestFullTier:
    def test_no_hints_full_scan(self):
        plan = make_plan(None, None, make_caps([]))
        assert plan.mode == "full"
        assert plan.fetch(None) == ROWS

    def test_fetch_all_receives_wants(self):
        # Every tier gets `wants`, not just the index tier - it's what lets a
        # full-tier resource (decks) skip building expensive fields.
        seen = []
        caps = SourceCaps(fetch_all=lambda wants=None: seen.append(wants) or list(ROWS))
        make_plan(None, None, caps).fetch({"id", "name"})
        assert seen == [{"id", "name"}]

    def test_index_beats_columns(self):
        # where on an indexed path wins even when select could use columns
        calls = []
        plan = make_plan("id,name", ["id==2"], make_caps(calls))
        assert plan.mode == "index"
