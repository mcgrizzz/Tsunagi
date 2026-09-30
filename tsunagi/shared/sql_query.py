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
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

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


def compile_where(source: ColumnSource, where: Optional[List[str]]) -> Compiled:
    parts: List[str] = []
    args: List[Any] = []
    for text in where or []:
        clause = parse_where(text)
        if len(clause.tokens) != 1:
            continue
        name = clause.tokens[0]
        if name in source.columns:
            done = _pushed(source.columns[name], clause)
        elif name in source.restrictions:
            done = _restricted(source.restrictions[name], clause)
        else:
            done = None
        if done is not None:
            parts.append(f"({done[0]})")
            args.extend(done[1])
    return Compiled(" and ".join(parts), tuple(args), len(parts))


def _where(*conditions: str) -> str:
    kept = [c for c in conditions if c]
    return " where " + " and ".join(kept) if kept else ""


def page_ids(source: ColumnSource, compiled: Compiled, after: Optional[int], limit: int) -> List[int]:
    """The next ids after `after`, ascending: the keyset page with the where built in."""
    keyset = "id > ?" if after is not None else ""
    sql = f"select id from {source.table}{_where(keyset, compiled.condition)} order by id limit ?"
    return source.run(sql, ([int(after)] if after is not None else []) + list(compiled.args) + [int(limit)])


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
