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

# Query operations. Every fetcher takes `wants` so a resource can skip building
# expensive fields nobody asked for, whichever tier ends up serving the query.
FetchAllFn       = Callable[[Wants], List[Row]]
FetchValuesFn    = Callable[[Sequence[Any], Wants], List[Row]]
FetchColumnsFn   = Callable[[Wants], List[Row]]
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

# Keyset id enumeration: (after_key, limit) -> the next ids. The contract the
# cursor math depends on: ascending, unique, and strictly greater than
# after_key (None = from the start). SQL provides this for free; anything
# else must guarantee it or pagination silently skips/repeats rows.
PageIdsFn        = Callable[[Optional[int], int], List[int]]


@dataclass(frozen=True)
class SearchSpec:
    """
    Backend search (Anki's own query language). Two-phase on purpose: ids are
    cheap to enumerate, so we page them first and hydrate only the page -
    a 100k-note collection never materializes.
    """
    find_ids: SearchIdsFn                  # (query) -> ids
    hydrate: FetchValuesFn                 # normally the SAME fn as IndexSpec(("id",)).fetch_values
    # Optional keyset pushdown for the bare listing (the scan tier). A real
    # search query can't use it - Anki search ids only come as a full list.
    page_ids: Optional[PageIdsFn] = None
    # Opt in when the enumerated IDs are existing values of this public field.
    # An ID-only query can use them without loading the same records again.
    id_field: Optional[str] = None
    # Optional one-pass read: (query, wants) -> every matching row, ascending
    # by id and unique, exactly as enumerating then hydrating would return
    # them. Used only for a complete, unfiltered result (no where, limit or
    # cursor), where collecting ids first is wasted work. The empty query
    # means the whole collection.
    rows: Optional[Callable[[str, Optional[Set[str]]], List[Any]]] = None


@dataclass(frozen=True)
class ScanSpec:
    """Enumerate lightweight IDs without exposing Anki browser search."""
    find_ids: BoundIdsFn
    hydrate: FetchValuesFn

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
    scan: Optional[ScanSpec] = None
    # Fields built by the same costly hydration step. Defer a group only when
    # the predicate does not already need that work (e.g. question and answer).
    expensive_groups: tuple[FrozenSet[str], ...] = ()

@dataclass
class Plan:
    mode: str                                  # 'search'|'scan'|'index'|'columns'|'full'
    fetch: Optional[FetchAllFn] = None         # materialize-everything tiers
    # Search/scan tiers: enumerate ids cheaply, then hydrate a page at a time.
    # The caller drives the loop because it owns `where` filtering.
    find_ids: Optional[BoundIdsFn] = None
    hydrate: Optional[FetchValuesFn] = None
    # Scan tier only: keyset id enumeration, so a bare listing (or a
    # where-filtered one) never materializes the full id list.
    page_ids: Optional[PageIdsFn] = None
    # Search-backed tiers: every row in one read (see SearchSpec.rows).
    rows: Optional[Callable[[Optional[Set[str]]], List[Any]]] = None

def _dedupe_indices(xs):
    seen = {}
    out = []
    for x in xs:          # dicts are insertion-ordered (Py3.7+)
        if x not in seen:
            seen[x] = None
            out.append(x)
    return out


def _index_values(idx: IndexSpec, clause: Any) -> List[Scalar]:
    """
    The values a where clause contributes to this index - coerced and deduped,
    empty when the clause can't drive it (wrong path, wrong op, or nothing
    usable after coercion). Dropping an uncoercible value only NARROWS the
    prefetch: it could never have matched a real row, and the full where
    predicate still runs on whatever the index returns.
    """
    if tuple(clause.tokens) != idx.path:
        return []
    if clause.op == "==":
        vals = [clause.value]
    elif clause.op == "in" and isinstance(clause.value, list):
        vals = list(clause.value)
    else:
        return []

    scalars: List[Scalar] = [v for v in vals
                             if isinstance(v, (str, int, float, bool)) or v is None]
    if idx.coerce is not None:
        coerced: List[Scalar] = []
        for v in scalars:
            nv = idx.coerce(v)
            if nv is not None:
                coerced.append(nv)
        scalars = coerced
    return _dedupe_indices(scalars)


def _index_plan(caps: SourceCaps, where_params: Optional[List[str]]) -> Optional[Plan]:
    """The first (index, clause) pair with usable values wins."""
    if not (caps.indices and where_params):
        return None
    for idx in caps.indices:
        for w in where_params:
            scalars = _index_values(idx, parse_where(w))
            if not scalars:
                continue
            if idx.path == ("id",):
                # The values ARE the row keys, so the id-tier machinery can
                # page and chunk them: `where=id in [10k ids]&limit=50` used
                # to hydrate all 10k per page; now it hydrates a page.
                return Plan("index", find_ids=lambda vals=scalars: vals,
                            hydrate=idx.fetch_values)
            # Secondary index (note_id, card_id, ...): values are not row
            # keys - one value fans out to many rows and the cursor walks
            # ROW ids - so fetch everything and paginate in memory. Result
            # size is bounded by the values the caller listed.
            return Plan("index", fetch=lambda wants=None, idx=idx, vals=scalars:
                        idx.fetch_values(vals, wants))
    return None


def _columns_plan(caps: SourceCaps, select_text: Optional[str],
                  where_params: Optional[List[str]]) -> Optional[Plan]:
    if not caps.columns_fetchers:
        return None
    tops = selected_top_fields(select_text)
    if not tops:
        return None
    # The where predicate runs on these rows too, so every top-level
    # field a clause touches must also be present in the fetched
    # columns - otherwise filters silently match nothing.
    needed = set(tops)
    for w in (where_params or []):
        needed.add(parse_where(w).tokens[0])
    for fs, fetcher in caps.columns_fetchers.items():
        if needed.issubset(fs):
            return Plan("columns", fetcher)
    return None


def _search_hydrator(spec: SearchSpec) -> FetchValuesFn:
    def hydrate(ids, wants=None):
        if spec.id_field is not None and wants == {spec.id_field}:
            return [{spec.id_field: int(value)} for value in ids]
        return spec.hydrate(ids, wants)

    return hydrate


def _search_rows(spec: SearchSpec, query: str) -> Optional[Callable[[Optional[Set[str]]], List[Any]]]:
    if spec.rows is None:
        return None
    return lambda wants: spec.rows(query, wants)


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
        return Plan("search", find_ids=lambda: spec.find_ids(q), hydrate=_search_hydrator(spec),
                    rows=_search_rows(spec, q))

    # 1) INDEX FIRST — ex: User wants to grab models by id
    plan = _index_plan(caps, where_params)
    if plan is not None:
        return plan

    # 2) COLUMNS FAST PATH — ex: User only wants (id,name) from models we have an alternate route to fetch that
    plan = _columns_plan(caps, select_text, where_params)
    if plan is not None:
        return plan

    # 3) PAGE BEFORE HYDRATION for resources with a lightweight ID listing.
    if caps.scan is not None:
        return Plan("scan", find_ids=caps.scan.find_ids, hydrate=caps.scan.hydrate)

    # 4) FALLBACK
    if caps.fetch_all is not None:
        return Plan("full", caps.fetch_all)

    # 5) SCAN — search-backed resources with no fetch_all: a bare listing is
    # the same path as a search, with the empty query (= whole collection).
    # When the source can enumerate ids keyset-style, hand that through so
    # the page never materializes the full id list.
    if caps.search is not None:
        spec = caps.search
        return Plan("scan", find_ids=lambda: spec.find_ids(""),
                    hydrate=_search_hydrator(spec), page_ids=spec.page_ids,
                    rows=_search_rows(spec, ""))

    raise ValueError("resource has no way to enumerate rows")
