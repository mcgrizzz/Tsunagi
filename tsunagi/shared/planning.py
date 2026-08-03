from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from .filtering import parse_where  # we'll read ops & tokens directly
from .schemas.wrappers import Scalar
from .selecting import selected_top_fields

Row = Union[Mapping[str, Any], Any]

# Set of top-level field names the caller asked for (via select/where), or None
# for "the whole record". Fetchers use it to skip expensive fields.
Wants = Optional[Set[str]]

# Query operations
FetchAllFn       = Callable[[], List[Row]]
FetchValuesFn    = Callable[[Sequence[Any], Wants], List[Row]]
FetchColumnsFn   = Callable[[], List[Row]]
CoerceFn         = Callable[[Any], Optional[Any]]
SearchIdsFn      = Callable[[str], List[int]]
BoundIdsFn       = Callable[[], List[int]]     # search query already bound

# Mutation operations
CreateFn         = Callable[[Dict[str, Any]], Row]                    # (data) -> result (for top-level create)
PatchFn          = Callable[[int, Dict[str, Any]], Row]              # (id, updates) -> result (for top-level patch)
DeleteFn         = Callable[[int], bool]                              # (id) -> success (for top-level delete)

# Subresource mutation operations
SubresourceCreateFn  = Callable[[int, Dict[str, Any]], Row]          # (parent_id, data) -> result
SubresourcePatchFn   = Callable[[int, Any, Dict[str, Any]], Row]    # (parent_id, sub_id, updates) -> result
SubresourceDeleteFn  = Callable[[int, Any], Row]                     # (parent_id, sub_id) -> result
SubresourceReorderFn = Callable[[int, List[Any]], Row]               # (parent_id, order) -> result

# ---- Capabilities ----

@dataclass(frozen=True)
class IndexSpec:
    path: Tuple[str, ...]                  # e.g. ("id",) or ("nid",) or ("cid",)
    fetch_values: FetchValuesFn            # called with ([values], wants) for == / in filters
    coerce: Optional[CoerceFn] = None #Force the index into the correct type, returning None on invalid value

@dataclass(frozen=True)
class SearchSpec:
    """
    Backend search (Anki's own query language). Two-phase on purpose: ids are
    cheap to enumerate, so we page them first and hydrate only the page -
    a 100k-note collection never materializes.
    """
    find_ids: SearchIdsFn                  # (query) -> ids
    hydrate: FetchValuesFn                 # normally the SAME fn as IndexSpec(("id",)).fetch_values

# Subresource Mutation Capabilities
@dataclass
class SubresourceMutations:
    """Define mutations for a sub-resource (e.g., fields, templates)"""
    json_key: str                                      # Key in parent dict (e.g., "flds", "tmpls")
    path_name: Optional[str] = None                   # URL path name (e.g., "fields"), defaults to json_key
    id_field: str = "name"                             # Field to use as identifier (e.g., "name", "ord", "id")
    id_type: str = "str"                               # Type for path parameter: "str" or "int"
    create: Optional[SubresourceCreateFn] = None
    patch: Optional[SubresourcePatchFn] = None
    delete: Optional[SubresourceDeleteFn] = None
    reorder: Optional[SubresourceReorderFn] = None

# Mutation Capabilities
@dataclass
class MutationCaps:
    create: Optional[CreateFn] = None
    patch: Optional[PatchFn] = None
    delete: Optional[DeleteFn] = None
    subresources: Dict[str, SubresourceMutations] = field(default_factory=dict)

# Source Capabilities
@dataclass
class SourceCaps:
    # Optional: resources backed by search (notes) deliberately supply none, so
    # materializing every row is unreachable.
    fetch_all: Optional[FetchAllFn] = None
    indices: Optional[List[IndexSpec]] = None                                # optional list of indices
    columns_fetchers: Optional[Dict[FrozenSet[str], FetchColumnsFn]] = None # optional: exact top-level sets → fetcher
    search: Optional[SearchSpec] = None                                      # optional: backend search
    mutations: Optional[MutationCaps] = None                                 # optional: mutation operations

@dataclass
class Plan:
    mode: str                                  # 'search'|'scan'|'index'|'columns'|'full'
    fetch: Optional[FetchAllFn] = None         # materialize-everything tiers
    # Search/scan tiers: enumerate ids cheaply, then hydrate a page at a time.
    # The caller drives the loop because it owns `where` filtering.
    find_ids: Optional[BoundIdsFn] = None
    hydrate: Optional[FetchValuesFn] = None

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
    search: Optional[str] = None,
) -> Plan:
    # 0) SEARCH FIRST — a correctness constraint, not a speed heuristic: the
    # other tiers can't evaluate Anki search syntax, so letting one of them win
    # would silently drop the search terms.
    if search is not None:
        if caps.search is None:
            raise ValueError("search is not supported for this resource")
        spec, q = caps.search, search
        return Plan("search", find_ids=lambda: spec.find_ids(q), hydrate=spec.hydrate)

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

                return Plan("index", fetch=lambda wants=None, idx=idx, vals=scalars:
                            idx.fetch_values(vals, wants))

    # 2) COLUMNS FAST PATH — ex: User only wants (id,name) from models we have an alternate route to fetch that
    if caps.columns_fetchers:
        tops = selected_top_fields(select_text)
        if tops:
            # The where predicate runs on these rows too, so every top-level
            # field a clause touches must also be present in the fetched
            # columns - otherwise filters silently match nothing.
            needed = set(tops)
            for w in (where_params or []):
                needed.add(parse_where(w).tokens[0])
            for fs, fetcher in caps.columns_fetchers.items():
                if needed.issubset(fs):
                    return Plan("columns", fetcher)

    # 3) FALLBACK
    if caps.fetch_all is not None:
        return Plan("full", caps.fetch_all)

    # 4) SCAN — search-backed resources with no fetch_all: a bare listing is
    # the same path as a search, with the empty query (= whole collection).
    if caps.search is not None:
        spec = caps.search
        return Plan("scan", find_ids=lambda: spec.find_ids(""), hydrate=spec.hydrate)

    raise ValueError("resource has no way to enumerate rows")
