"""
The parts of a query SQL can answer exactly, for resources whose row fields
are table columns (cards, notes, reviews; backlog 9.13).

A `where` clause is pushed into SQL only when SQL gives the same answer as the
Python predicate (filtering.py) for every row: an integer column compared with
an integer (never a bool: the DSL doesn't treat true as 1), a bool column with
true/false, a text column with a string for equality and membership. `~=`
stays in Python: SQLite's lower() folds only ASCII, the DSL folds Unicode.
Everything not pushed is left to the Python predicate, which still runs on
every row the SQL returns (the completeness invariant).

Pure: no Anki imports. A resource's adapter supplies `run`, which executes
the SQL inside its QueryOp and returns ids.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .filtering import Clause, parse_where

SEARCH_CHUNK = 5000  # search ids per filtering query; ids are ints we interpolate


@dataclass(frozen=True)
class Column:
    sql: str    # column or expression, in terms of the source's table
    kind: str   # "int", "bool" or "text"


# (values of an == or `in` clause) -> a SQL condition matching a superset of
# the rows, or None when it can't help. For fields that aren't columns but
# have an index behind them, such as a note's first field (its checksum).
Restriction = Callable[[List[Any]], Optional[Tuple[str, List[Any]]]]


@dataclass(frozen=True)
class ColumnSource:
    table: str
    columns: Mapping[str, Column]
    run: Callable[[str, Sequence[Any]], List[int]]   # (sql, args) -> ids
    restrictions: Mapping[str, Restriction] = field(default_factory=dict)
    rows: Optional[Callable[[str, Sequence[Any]], List[Sequence[Any]]]] = None   # (sql, args) -> rows
    # (Anki search) -> a SQL condition on this table for what it matches, when
    # that is cheaper than the id list (reviews: `cid in (...)`).
    search_condition: Optional[Callable[[str], Tuple[str, Sequence[Any]]]] = None


def _is_int(v: Any) -> bool:
    return type(v) is int


_MATCHES = {"int": _is_int, "bool": lambda v: type(v) is bool, "text": lambda v: type(v) is str}
_SQL_OPS = {"==": "=", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


def _pushed(column: Column, clause: Clause) -> Optional[Tuple[str, List[Any]]]:
    ok = _MATCHES[column.kind]
    if clause.op in ("in", "not in"):
        values = clause.value
        if not isinstance(values, list) or not values or not all(ok(v) for v in values):
            return None
        marks = ",".join("?" for _ in values)
        return f"({column.sql}) {clause.op} ({marks})", [int(v) if column.kind == "bool" else v for v in values]
    if clause.op not in _SQL_OPS or not ok(clause.value):
        return None
    if clause.op not in ("==", "!=") and column.kind != "int":
        return None  # ordering stays exact only for integers
    value = int(clause.value) if column.kind == "bool" else clause.value
    return f"({column.sql}) {_SQL_OPS[clause.op]} ?", [value]


def _restricted(restriction: Restriction, clause: Clause) -> Optional[Tuple[str, List[Any]]]:
    if clause.op == "==":
        return restriction([clause.value])
    if clause.op == "in" and isinstance(clause.value, list) and clause.value:
        return restriction(list(clause.value))
    return None


@dataclass(frozen=True)
class Compiled:
    condition: str        # "" when nothing was pushed
    args: Tuple[Any, ...]
    pushed: int           # clauses answered (exactly or as a superset) in SQL
    exact: int = 0        # of those, the ones SQL answers exactly (not a superset)


def compile_where(source: ColumnSource, where: Optional[List[str]]) -> Compiled:
    parts: List[str] = []
    args: List[Any] = []
    exact = 0
    for text in where or []:
        clause = parse_where(text)
        if len(clause.tokens) != 1:
            continue
        name = clause.tokens[0]
        if name in source.columns:
            done = _pushed(source.columns[name], clause)
            exact += done is not None
        elif name in source.restrictions:
            done = _restricted(source.restrictions[name], clause)
        else:
            done = None
        if done is not None:
            parts.append(f"({done[0]})")
            args.extend(done[1])
    return Compiled(" and ".join(parts), tuple(args), len(parts), exact)


def _where(*conditions: str) -> str:
    kept = [c for c in conditions if c]
    return " where " + " and ".join(kept) if kept else ""


def page_ids(source: ColumnSource, compiled: Compiled, after: Optional[int], limit: int) -> List[int]:
    """The next ids after `after`, ascending: the keyset page with the where built in."""
    keyset = "id > ?" if after is not None else ""
    sql = f"select id from {source.table}{_where(keyset, compiled.condition)} order by id limit ?"
    return source.run(sql, ([int(after)] if after is not None else []) + list(compiled.args) + [int(limit)])


def count(source: ColumnSource, compiled: Compiled, condition: str = "",
          condition_args: Sequence[Any] = ()) -> int:
    """How many rows the pushed clauses (and a search's `condition`) match."""
    return int(source.run(f"select count(*) from {source.table}{_where(condition, compiled.condition)}",
                          list(condition_args) + list(compiled.args))[0])


def all_ids(source: ColumnSource, compiled: Compiled) -> List[int]:
    return source.run(f"select id from {source.table}{_where(compiled.condition)} order by id",
                      list(compiled.args))


def filter_ids(source: ColumnSource, compiled: Compiled, ids: Sequence[int]) -> List[int]:
    """The ids (a search's result) that also meet the pushed clauses, ascending."""
    out: List[int] = []
    ordered = sorted({int(i) for i in ids})
    for start in range(0, len(ordered), SEARCH_CHUNK):
        chunk = ",".join(str(i) for i in ordered[start:start + SEARCH_CHUNK])
        out.extend(source.run(
            f"select id from {source.table}{_where(f'id in ({chunk})', compiled.condition)} order by id",
            list(compiled.args)))
    return out


def first_per_value(source: ColumnSource, name: str, ids: Sequence[int]) -> List[int]:
    """`ids`, in their order, keeping the first of each value of the column
    `name`: what `distinct_on` returns (backlog 8.12). A null is a value too."""
    assert source.rows is not None
    expr = source.columns[name].sql
    values: Dict[int, Any] = {}
    ordered = sorted({int(i) for i in ids})
    for start in range(0, len(ordered), SEARCH_CHUNK):
        chunk = ",".join(str(i) for i in ordered[start:start + SEARCH_CHUNK])
        values.update((int(row[0]), row[1]) for row in source.rows(
            f"select id, ({expr}) from {source.table} where id in ({chunk})", []))
    seen: set = set()
    out: List[int] = []
    for i in ids:
        if i in values and values[i] not in seen:
            seen.add(values[i])
            out.append(i)
    return out


def first_by_id(source: ColumnSource, name: str, compiled: Compiled, descending: bool,
                ids: Optional[Sequence[int]] = None, condition: str = "",
                condition_args: Sequence[Any] = ()) -> List[int]:
    """`distinct_on` when the order is by id: each value's lowest id (highest
    when descending) in one grouped query, which walks the column's index when
    it has one (revlog `cid`). `ids` (a search's result) are grouped a chunk at
    a time and merged; `condition` is a search already in SQL."""
    agg = "max" if descending else "min"
    expr = source.columns[name].sql
    args = list(condition_args) + list(compiled.args)
    if ids is None:
        found = source.run(f"select {agg}(id) from {source.table}{_where(condition, compiled.condition)} "
                           f"group by ({expr})", args)
    else:
        assert source.rows is not None
        best: Dict[Any, int] = {}
        ordered = sorted({int(i) for i in ids})
        for start in range(0, len(ordered), SEARCH_CHUNK):
            chunk = ",".join(str(i) for i in ordered[start:start + SEARCH_CHUNK])
            for value, rid in source.rows(
                    f"select ({expr}), {agg}(id) from {source.table}"
                    f"{_where(f'id in ({chunk})', condition, compiled.condition)} group by ({expr})", args):
                if value not in best or (rid > best[value] if descending else rid < best[value]):
                    best[value] = int(rid)
        found = list(best.values())
    return sorted((int(i) for i in found), reverse=descending)
