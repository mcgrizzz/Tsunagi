from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple, Union

from .selecting import selected_top_fields
from .filtering import parse_where  # we’ll read ops & tokens directly
from .schemas.wrappers import Scalar

Row = Union[Mapping[str, Any], Any]

# Query operations
FetchAllFn       = Callable[[], List[Row]]
FetchValuesFn    = Callable[[Sequence[Any]], List[Row]]
FetchColumnsFn   = Callable[[], List[Row]]
CoerceFn         = Callable[[Any], Optional[Any]]

# Mutation operations
CreateFn         = Callable[[Dict[str, Any]], Row]
PatchFn          = Callable[[int, Dict[str, Any]], Row]
DeleteFn         = Callable[[int], bool]

# ---- Capabilities ----

@dataclass(frozen=True)
class IndexSpec:
    path: Tuple[str, ...]                  # e.g. ("id",) or ("nid",) or ("cid",)
    fetch_values: FetchValuesFn            # called with [values] for == / in filters
    coerce: Optional[CoerceFn] = None #Force the index into the correct type, returning None on invalid value

# Mutation Capabilities
@dataclass
class MutationCaps:
    create: Optional[CreateFn] = None
    patch: Optional[PatchFn] = None
    delete: Optional[DeleteFn] = None

# Source Capabilities
@dataclass
class SourceCaps:
    fetch_all: FetchAllFn                                                    # required
    indices: Optional[List[IndexSpec]] = None                                # optional list of indices
    columns_fetchers: Optional[Dict[FrozenSet[str], FetchColumnsFn]] = None # optional: exact top-level sets → fetcher
    mutations: Optional[MutationCaps] = None                                 # optional: mutation operations

@dataclass
class Plan:
    mode: str                     # 'index' | 'columns' | 'full'
    fetch: FetchAllFn

def _dedupe_indices(xs):
    seen = {}
    out = []
    for x in xs:          # dicts are insertion-ordered (Py3.7+)
        if x not in seen:
            seen[x] = None
            out.append(x)
    return out


def make_plan(
    select_text: Optional[str],
    where_params: Optional[List[str]],
    caps: SourceCaps,
) -> Plan:
    # 1) INDEX FIRST — ex: User wants to grab models by id
    if caps.indices and where_params:
        for idx in caps.indices:                 
            for w in where_params:               
                c = parse_where(w)
                if tuple(c.tokens) != idx.path:
                    continue
                if c.op == "==":
                    vals = [c.value]
                elif c.op == "in" and isinstance(c.value, list):
                    vals = list(c.value)
                else:
                    continue

                scalars: List[Scalar] = [v for v in vals if isinstance(v, (str, int, float, bool)) or v is None]
                if idx.coerce is not None:
                    coerced: List[Scalar] = []
                    for v in scalars:
                        nv = idx.coerce(v)
                        if nv is not None:
                            coerced.append(nv)
                    scalars = coerced

                scalars = _dedupe_indices(scalars)
                if not scalars:
                    continue

                return Plan("index", fetch=lambda idx=idx, vals=vals: idx.fetch_values(vals))

    # 2) COLUMNS FAST PATH — ex: User only wants (id,name) from models we have an alternate route to fetch that
    if caps.columns_fetchers:
        tops = selected_top_fields(select_text)
        if tops:
            for fs, fetcher in caps.columns_fetchers.items():
                if tops.issubset(fs):
                    return Plan("columns", fetcher)

    # 3) FALLBACK
    return Plan("full", caps.fetch_all)
