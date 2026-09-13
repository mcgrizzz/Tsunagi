import builtins

import pytest

from tsunagi.shared import filtering


@pytest.mark.parametrize(
    "query,row,expected",
    [
        ("value in [1,2,2]", {"value": 2}, True),
        ("value not in [1,2]", {"value": 3}, True),
        ("value in []", {"value": 1}, False),
        ("value not in []", {"value": 1}, True),
        ("value not in []", {}, False),
        ("value in [null]", {"value": None}, False),
        ("value not in [1]", {"value": None}, False),
        # Keep the existing hashed membership equality rules.
        ("value in [true]", {"value": 1}, True),
        ("value in [1]", {"value": 1.0}, True),
        ("value in [false]", {"value": 0}, True),
        ('value in [1]', {"value": "1"}, False),
        ('value in ["İ","犬",null,1.5]', {"value": "犬"}, True),
        ('value in ["İ"]', {"value": "i"}, False),
        ("value in [1]", {"value": [1]}, False),
        ("value not in [1]", {"value": {"a": 1}}, True),
        ("values[] in [null]", {"values": [None]}, True),
        ("values[] in [2]", {"values": [1, 2]}, True),
        ("values[] not in [2]", {"values": [1, 2]}, False),
        ("values[] not in [2]", {"values": [1, 3]}, True),
        ("values[] not in []", {"values": []}, False),
        ("values[] not in [2]", {"values": 3}, False),
        ("fields[].name in [Front]", {"fields": [{}, {"name": "Front"}]}, True),
        ("fields[].name not in [Front]", {"fields": [{}]}, False),
        ("groups[].values[] in [2]", {"groups": [{"values": [1]}, {"values": [2]}]}, True),
    ],
)
def test_membership_behavior(query, row, expected):
    assert filtering.build_predicate([query])(row) is expected


@pytest.mark.parametrize("negate", [False, True])
def test_unhashable_query_values_keep_strict_linear_matching(negate):
    # Not produced by the current grammar, but retain the operator fallback.
    match = filtering._compile_membership([[1], True], negate=negate)
    assert match(iter([[1]])) is (not negate)
    assert match(iter([1])) is negate
    assert match(iter([True])) is (not negate)
    assert match(iter([])) is negate
    assert filtering._compile_membership("invalid", negate=negate)([1]) is False


def test_membership_prepares_constants_once_and_reads_changed_rows(monkeypatch):
    calls = []

    def counted_set(values):
        calls.append(tuple(values))
        return builtins.set(values)

    monkeypatch.setattr(filtering, "set", counted_set, raising=False)
    queries = ["value in [1,2]", "other not in [3,4]", "active==true"]
    predicate = filtering.build_predicate(queries)
    assert calls == [(1, 2), (3, 4)]
    row = {"value": 1, "other": 5, "active": True}
    for _ in range(20):
        assert predicate(row)
    row["value"] = 6
    assert not predicate(row)
    row.update(value=2, other=3)
    assert not predicate(row)
    row.update(other=5, active=False)
    assert not predicate(row)
    assert calls == [(1, 2), (3, 4)]
    assert filtering.parse_where(queries[0]).value == [1, 2]
    assert filtering.parse_where(queries[1]).value == [3, 4]
    # Another query must use its own constants, even for the same row path.
    assert filtering.build_predicate(["value in [6]"])({"value": 6})
    assert not predicate({"value": 6, "other": 5, "active": True})


def test_membership_still_short_circuits_array_reads():
    class Unreadable(dict):
        def __contains__(self, key):
            raise AssertionError("accessed an unnecessary array element")

    row = {"fields": [{"name": "Front"}, Unreadable()]}
    assert filtering.build_predicate(["fields[].name in [Front]"])(row)
    assert not filtering.build_predicate(["fields[].name not in [Front]"])(row)
