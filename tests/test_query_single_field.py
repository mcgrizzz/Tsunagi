"""The single-field shortcut in _finish matches the general projection path."""

from __future__ import annotations

import time
from enum import IntEnum

import pytest

from tsunagi.shared.route_factory import _finish
from tsunagi.shared.selecting import (
    SelectValidationError,
    maybe_flatten,
    parse_select_csv,
    project_scalars,
)


class Flag(IntEnum):
    ON = 1


def general(rows, select, shape):
    nodes = parse_select_csv(select)
    return maybe_flatten([project_scalars(dict(r), nodes) for r in rows], nodes, shape or "auto")


ROWS = [
    [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
    [{"id": 1}, {"name": "missing id"}],
    [{"id": 1, "tags": ["x"]}, {"id": 2, "tags": []}],
    [{"id": 1, "flag": Flag.ON}, {"id": 2, "flag": True}],
    [{"id": 1, "score": 1.5}, {"id": 2, "score": None}],
    [],
]


@pytest.mark.parametrize("rows", ROWS)
@pytest.mark.parametrize("select", ["id", "name", "tags", "flag", "score", "id:nid", "name,id", "id:nid,name", "id,id", "score,flag,id"])
@pytest.mark.parametrize("shape", [None, "auto", "object"])
def test_matches_general_projection(rows, select, shape):
    page = _finish(rows, None, select, shape, time.perf_counter())
    assert page.items == general(rows, select, shape)
    assert [type(v) for v in page.items] == [type(v) for v in general(rows, select, shape)]


def test_scalar_shape_still_rejects_non_scalar_values():
    rows = [{"id": 1, "tags": ["x"]}]
    with pytest.raises(SelectValidationError):
        _finish(rows, None, "tags", "scalar", time.perf_counter())
    assert _finish(rows, None, "id", "scalar", time.perf_counter()).items == [1]


def test_envelope_keeps_cursor_and_stats():
    page = _finish([{"id": 1}], "cursor", "id", None, time.perf_counter())
    assert page.next_cursor == "cursor" and "duration_ms" in page.stats
    assert page.__fields_set__ == {"items", "next_cursor", "stats"}
