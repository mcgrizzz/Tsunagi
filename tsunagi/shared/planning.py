from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple, Union

from .selecting import selected_top_fields
from .filtering import parse_where  # we’ll read ops & tokens directly

Row = Union[Mapping[str, Any], Any]
FetchAllFn       = Callable[[], List[Row]]
FetchValuesFn    = Callable[[List[int]], List[Row]]       # for index-based fetch
FetchColumnsFn   = Callable[[], List[Row]]                # for selection-based fast path

# ---- Capabilities ----

@dataclass(frozen=True)
class IndexSpec:
    path: Tuple[str, ...]                  # e.g. ("id",) or ("nid",) or ("cid",)
    fetch_values: FetchValuesFn            # called with [values] for == / in filters

@dataclass
class SourceCaps:
    fetch_all: FetchAllFn                                # required
    indices: Optional[List[IndexSpec]] = None                      # optional list of indices
    columns_fetchers: Optional[Dict[FrozenSet[str], FetchColumnsFn]] = None  # optional: exact top-level sets → fetcher

@dataclass
class Plan:
    mode: str                     # 'index' | 'columns' | 'full'
    fetch: Callable[[], List[Row]]

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
