from __future__ import annotations

import logging
import re
import time
from bisect import bisect_right
from operator import itemgetter
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Union,
    get_args,
)

from fastapi import APIRouter, Body, HTTPException, Path, Query
from fastapi.responses import Response
from pydantic import BaseModel

from ..shared.pagination import (
    decode_cursor,
    decode_order_cursor,
    encode_cursor,
    paginate_keyset,
)
from ..shared.schemas.wrappers import (
    DeletionResult,
    MutationResult,
    Paginated,
    ProjectedObject,
    QueryRequest,
    Scalar,
)
from .errors import (
    AnkiBusyError,
    CollectionUnavailableError,
    handle_mutation_errors,
    track_operation,
)
from .filtering import build_predicate, parse_where
from .model_export import model_row_dict
from .permissions import requires
from .planning import SourceCaps, _search_hydrator, make_plan
from .query_encoding import render_query_page
from .selecting import (
    SelectScalar,
    maybe_flatten,
    parse_select_csv,
    project_scalars,
    referenced_top_fields,
    selection_include,
)
from .sql_query import compile_where, filter_ids

Row = Union[Mapping[str, Any], Any]
ModelRow = Union[Any, ProjectedObject, Scalar]
_SCALAR_TYPESET = frozenset(get_args(Scalar))

# Hydration runs inside a QueryOp with a wall-clock timeout, so a page is
# fetched in bounded slices rather than one call: each slice gets its own
# budget, and a large `limit` can't turn a slow page into a 503.
HYDRATE_CHUNK = 250

def _stats(start_time: float) -> dict:
    duration_ms = (time.perf_counter() - start_time) * 1000.0
    return {"duration_ms": round(duration_ms, 3)}

def _plain(x: Any) -> Any:
    # Serialize schema rows to human field names ourselves. FastAPI's
    # _prepare_response_content calls .dict(by_alias=True) on BaseModels
    # BEFORE response validation, so response_model_by_alias=False never
    # reaches rows typed as Any - Anki wire aliases would leak through.
    return model_row_dict(x) if isinstance(x, BaseModel) else x

def _as_dict(x: Any, include: Optional[Union[set, dict]] = None) -> Mapping[str, Any]:
    # Use the schema's human-readable field names (fields, templates,
    # sort_field) as the canonical keys for select/where. Aliases (flds,
    # tmpls, ...) remain available via `select` aliasing if a caller wants
    # Anki's wire names. This matches the non-aliased response output.
    if isinstance(x, Mapping):
        return x
    if isinstance(include, dict):
        # An array selector can target an irregular value. Do not reshape it
        # before glom has a chance to apply its existing fallback behavior.
        include = dict(include)
        for key, mask in include.items():
            if isinstance(mask, dict) and "__all__" in mask:
                value = getattr(x, key, None)
                if not isinstance(value, list) or not all(isinstance(v, (BaseModel, Mapping)) for v in value):
                    include[key] = True
    return model_row_dict(x, include=include)

def _finish(
    page_rows: List[Row],
    next_cursor: Optional[str],
    select: Optional[str],
    shape: Optional[str],
    start: float,
) -> Paginated[ModelRow]:
    """Project (if select) and wrap a page. Shared by all planner tiers."""
    # Items are typed Union[Any, ...]: validating them returns the same objects,
    # so construct() skips a per-item pass without changing the response.
    if not select:
        return Paginated[ModelRow].construct(items=[_plain(r) for r in page_rows],
                                             next_cursor=next_cursor, stats=_stats(start))
    nodes = parse_select_csv(select)
    final_items: Optional[List[ModelRow]] = None
    shape_name = (shape or "object").lower()
    top_level = (all(isinstance(n, SelectScalar) and len(n.path) == 1 for n in nodes)
                 and {type(r) for r in page_rows} <= {dict})
    if top_level and len(nodes) == 1 and shape_name == "scalar":
        # One top-level field from plain rows, e.g. select=id: read it directly
        # instead of building a projected dict per row and flattening it back.
        # Exact scalar types only; anything else takes the general path.
        values = [r.get(nodes[0].path[0]) for r in page_rows]
        if {type(v) for v in values} <= _SCALAR_TYPESET:
            final_items = values
    elif top_level and shape_name == "object":
        # Top-level fields: copy them in one C-level pass per row. A row
        # missing a field takes the general path, which fills it with None.
        names = [n.as_name or n.path[0] for n in nodes]
        if len(nodes) == 1:
            one = nodes[0].path[0]
            get = lambda r: (r[one],)  # itemgetter of one key returns the value, not a tuple
        else:
            get = itemgetter(*(n.path[0] for n in nodes))
        try:
            final_items = [dict(zip(names, get(r))) for r in page_rows]
        except KeyError:
            final_items = None
    if final_items is None:
        include = selection_include(nodes)
        projected = [project_scalars(_as_dict(r, include), nodes) for r in page_rows]
        final_items = maybe_flatten(projected, nodes, shape_name)
    return Paginated[ModelRow].construct(items=final_items, next_cursor=next_cursor,
                                         stats=_stats(start))

def _rehydrate(
    plan: Any,
    rows: List[Row],
    id_getter: Callable[[Row], int],
    wants: Optional[set],
) -> List[Row]:
    """
    Second phase of a two-phase filtered scan: the loop hydrated rows with
    only the fields the predicate needed; re-fetch the SURVIVING page with
    the caller's real want-set. A row deleted between phases just drops out -
    the same read-consistency non-guarantee pagination already has.
    """
    if not rows:
        return rows
    ids = [id_getter(r) for r in rows]
    by_id: Dict[int, Row] = {}
    for i in range(0, len(ids), HYDRATE_CHUNK):
        for r in plan.hydrate(ids[i:i + HYDRATE_CHUNK], wants):
            by_id[id_getter(r)] = r
    return [by_id[i] for i in ids if i in by_id]


def _keyset_scan(
    plan: Any,
    limit: Optional[int],
    cursor: Optional[str],
    wants: Optional[set],
    id_getter: Callable[[Row], int],
    pred: Optional[Callable[[Mapping[str, Any]], bool]],
    pred_wants: Optional[set] = None,
) -> tuple:
    """
    _paged_scan for a plan whose source enumerates ids keyset-style
    (plan.page_ids): same pages, same cursors, same completeness guarantee,
    but the full id list is never materialized. A limited, unfiltered page is
    one id query. Filtered and unlimited reads pull id chunks until the page
    fills (if limited) or the ids run out.
    """
    last_key = decode_cursor(cursor).get("last_key")

    if pred is None and limit is not None:
        ids = [int(i) for i in plan.page_ids(last_key, limit + 1)]
        page_ids, more = ids[:limit], len(ids) > limit
        rows: List[Row] = []
        for i in range(0, len(page_ids), HYDRATE_CHUNK):
            rows.extend(plan.hydrate(page_ids[i:i + HYDRATE_CHUNK], wants))
        return rows, (encode_cursor({"last_key": page_ids[-1]}) if more and page_ids else None)

    # Build deferred fields for the surviving page, not every rejected row.
    two_phase = pred_wants is not None
    scan_wants = pred_wants if two_phase else wants

    batch_size = HYDRATE_CHUNK if limit is None else max(min(limit, HYDRATE_CHUNK), 50)
    out: List[Row] = []
    key = last_key
    exhausted = False

    while not exhausted and (limit is None or len(out) < limit):
        chunk = [int(i) for i in plan.page_ids(key, batch_size)]
        if not chunk:
            break
        key = chunk[-1]
        exhausted = len(chunk) < batch_size
        out.extend(r for r in plan.hydrate(chunk, scan_wants) if pred is None or pred(_as_dict(r)))

    if limit is not None and len(out) > limit:
        out = out[:limit]
        cur = encode_cursor({"last_key": id_getter(out[-1])})
    elif not exhausted and len(out) == limit:
        cur = encode_cursor({"last_key": key})
    else:
        cur = None
    if two_phase:
        out = _rehydrate(plan, out, id_getter, wants)
    return out, cur


def _paged_scan(
    plan: Any,
    limit: Optional[int],
    cursor: Optional[str],
    wants: Optional[set],
    id_getter: Callable[[Row], int],
    pred: Optional[Callable[[Mapping[str, Any]], bool]],
    pred_wants: Optional[set] = None,
) -> tuple:
    """
    Walk the id list, hydrating a batch at a time until `limit` rows survive
    the filter or the ids run out.

    The guarantee is completeness: if a matching row exists anywhere in the
    collection, it is returned. `where` can't be pushed into Anki's search, so
    the only honest way to keep that promise is to keep scanning - a partial
    scan would mean "no results" for rows that do exist, and would force
    clients into retry loops. `limit` bounds the results, not the search.
    """
    if getattr(plan, "page_ids", None) is not None:
        return _keyset_scan(plan, limit, cursor, wants, id_getter, pred, pred_wants)

    last_key = decode_cursor(cursor).get("last_key")
    ids = sorted({int(i) for i in plan.find_ids()})
    if last_key is not None:
        ids = ids[bisect_right(ids, last_key):]   # sorted, so no linear scan

    if pred is None:
        page_ids, more = ids[:limit], limit is not None and len(ids) > limit
        rows: List[Row] = []
        for i in range(0, len(page_ids), HYDRATE_CHUNK):
            rows.extend(plan.hydrate(page_ids[i:i + HYDRATE_CHUNK], wants))
        return rows, (encode_cursor({"last_key": page_ids[-1]}) if more and page_ids else None)

    two_phase = pred_wants is not None
    scan_wants = pred_wants if two_phase else wants

    batch_size = HYDRATE_CHUNK if limit is None else max(min(limit, HYDRATE_CHUNK), 50)
    out: List[Row] = []
    examined = 0

    while examined < len(ids) and (limit is None or len(out) < limit):
        chunk = ids[examined:examined + batch_size]
        examined += len(chunk)
        out.extend(r for r in plan.hydrate(chunk, scan_wants) if pred(_as_dict(r)))

    if limit is not None and len(out) > limit:
        # Over-collected within a batch: cut to the page and resume from the
        # last INCLUDED row, so the surplus isn't skipped next time.
        out = out[:limit]
        cur = encode_cursor({"last_key": id_getter(out[-1])})
    elif examined < len(ids):
        cur = encode_cursor({"last_key": ids[examined - 1]})
    else:
        cur = None
    if two_phase:
        out = _rehydrate(plan, out, id_getter, wants)
    return out, cur

# ----- order= (backlog 8.1) -----

_ORDER = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*(asc|desc)\s*)?$", re.IGNORECASE)
_SCALARS = (str, int, float, bool)


def _parse_order(text: str) -> tuple:
    match = _ORDER.match(text or "")
    if not match:
        raise ValueError(f"Invalid order {text!r}: use a field name, optionally with :asc or :desc (e.g. due:desc)")
    return match.group(1), (match.group(2) or "asc").lower() == "desc"


def _cannot_order(name: str, names: Any) -> ValueError:
    return ValueError(f"Can't order by {name}. Order by: {', '.join(sorted(names))}")


def _order_start(keys: List[Any], cursor: Optional[str]) -> int:
    """Where the next page starts: after the last row sent, if it is still in
    the sorted list, else at the same position."""
    state = decode_order_cursor(cursor)
    if not state:
        return 0
    try:
        return keys.index(state["last"]) + 1
    except ValueError:
        return state["pos"]


def _order_cursor(keys: List[Any], next_pos: Optional[int], last: Any) -> Optional[str]:
    if next_pos is None or next_pos >= len(keys):
        return None
    return encode_cursor({"pos": next_pos, "last": last})


def _ordered_scan(ids: List[int], hydrate: Callable, limit: Optional[int], cursor: Optional[str],
                  wants: Optional[set], id_getter: Callable[[Row], Any],
                  pred: Optional[Callable[[Mapping[str, Any]], bool]]) -> tuple:
    """Walk ids in their sorted order, a chunk at a time, until the page fills."""
    i = _order_start(ids, cursor)
    batch = HYDRATE_CHUNK if limit is None else max(min(limit, HYDRATE_CHUNK), 50)
    out: List[Row] = []
    next_pos = None
    while i < len(ids) and next_pos is None:
        chunk = ids[i:i + batch]
        by_id = {id_getter(r): r for r in hydrate(chunk, wants)}  # hydration needn't keep the order
        for j, rid in enumerate(chunk):
            row = by_id.get(rid)
            if row is None or (pred is not None and not pred(_as_dict(row))):
                continue
            out.append(row)
            if limit is not None and len(out) == limit:
                next_pos = i + j + 1
                break
        i += len(chunk)
    return out, _order_cursor(ids, next_pos, id_getter(out[-1]) if out else None)


def _ordered_query(select, where, shape, limit, cursor, caps, id_getter, search, order, start):
    name, descending = _parse_order(order)
    wants = _wanted_fields(select, where)
    pred = build_predicate(where) if where else None
    if caps.order is not None:
        # Cards and notes: Anki's own sort; reviews: SQL. Then the same where
        # handling as unordered queries: SQL narrows, the predicate decides.
        names = caps.order.names()
        if name not in names:
            raise _cannot_order(name, names)
        ids = caps.order.ordered_ids(search or "", name, descending)
        compiled = compile_where(caps.sql, where) if caps.sql is not None and where else None
        if compiled is not None and compiled.pushed:
            keep = set(filter_ids(caps.sql, compiled, ids))
            ids = [i for i in ids if i in keep]
        rows, cur = _ordered_scan(ids, _search_hydrator(caps.search), limit, cursor, wants, id_getter, pred)
        return _finish(rows, cur, select, shape, start)

    # Small resources (decks, note types, presets): every matching row, sorted here.
    plan = make_plan(select, where, caps, search)
    need = None if wants is None else wants | {name}
    if plan.fetch is not None:
        rows = plan.fetch(need)
    else:
        found = [int(i) for i in plan.find_ids()]
        rows = [r for k in range(0, len(found), HYDRATE_CHUNK) for r in plan.hydrate(found[k:k + HYDRATE_CHUNK], need)]
    if pred is not None:
        rows = [r for r in rows if pred(_as_dict(r))]
    fields = {k for r in rows for k, v in _as_dict(r).items() if isinstance(v, _SCALARS)}
    if rows and name not in fields:
        raise _cannot_order(name, fields)

    def value(row: Row) -> tuple:
        v = _as_dict(row).get(name)
        return (v is None, v)
    rows.sort(key=id_getter)
    try:
        rows.sort(key=value, reverse=descending)  # stable: ties keep ascending id
    except TypeError:
        raise ValueError(f"Can't order by {name}: its values have different types") from None
    keys = [id_getter(r) for r in rows]
    first = _order_start(keys, cursor)
    page = rows[first:] if limit is None else rows[first:first + limit]
    cur = _order_cursor(keys, first + len(page) if limit is not None else None,
                        id_getter(page[-1]) if page else None)
    return _finish(page, cur, select, shape, start)


def _wanted_fields(select: Optional[str], where: Optional[List[str]]) -> Optional[set]:
    """
    Top-level fields the caller actually referenced, so fetchers can skip
    building expensive ones. None means "the whole record".
    """
    wants = referenced_top_fields(select)
    if wants is None:
        return None
    return wants | {parse_where(w).tokens[0] for w in (where or [])}

def _execute_query(
    select: Optional[str],
    where: Optional[List[str]],
    shape: Optional[str],
    limit: Optional[int],
    cursor: Optional[str],
    caps: SourceCaps,
    id_getter: Callable[[Row], int],
    search: Optional[str] = None,
    order: Optional[str] = None,
) -> Paginated[ModelRow]:
    """
    Core query execution logic shared between GET and POST routes.
    """
    start = time.perf_counter()
    try:
        if order:
            return _ordered_query(select, where, shape, limit, cursor, caps, id_getter, search, order, start)
        plan = make_plan(select, where, caps, search)
        wants = _wanted_fields(select, where)

        if plan.find_ids is not None:
            if getattr(plan, "rows", None) is not None and not where and limit is None and cursor is None:
                # The complete, unfiltered result: one read instead of
                # collecting ids and then hydrating them in slices.
                return _finish(plan.rows(wants), None, select, shape, start)
            # pred_wants: the fields the where predicate reads, plus the row
            # key - what phase one of a two-phase filtered scan hydrates.
            pred_wants = None
            if where:
                required = {parse_where(w).tokens[0] for w in where} | {"id"}
                if wants is None or any(
                    group & wants and not group & required
                    for group in caps.expensive_groups
                ):
                    pred_wants = required
            page_rows, next_cursor = _paged_scan(
                plan, limit, cursor, wants, id_getter,
                build_predicate(where) if where else None,
                pred_wants,
            )
            return _finish(page_rows, next_cursor, select, shape, start)

        rows = plan.fetch(wants)

        # Filter rows if where clauses provided
        if where:
            pred = build_predicate(where)
            rows = [r for r in rows if pred(_as_dict(r))]

        rows.sort(key=id_getter)
        page_rows, next_cursor = paginate_keyset(rows, limit, cursor, key_fn=id_getter)
        return _finish(page_rows, next_cursor, select, shape, start)

    except HTTPException:
        raise
    except (AnkiBusyError, CollectionUnavailableError):
        # Handled app-level (register_exception_handlers) -> 503
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception:
        logging.getLogger(__name__).exception("Query failed")
        raise HTTPException(status_code=500, detail="Internal error") from None

def create_resource_routes(
    path: str,
    *,
    caps: SourceCaps,
    response_model: Any,
    id_getter: Callable[[Row], int] = lambda r: int(r["id"] if isinstance(r, Mapping) else r.id),
    resource_name: str,
    resource_plural: str,
    tag: str,
    permission_resource: str,
    description: str = "",
    post_path: Optional[str] = None,
) -> APIRouter:
    """
    Create complete REST routes for a resource (queries + mutations).

    Args:
        path: Base path for resource (e.g., "/v1/models")
        caps: Source capabilities (queries + optional mutations)
        response_model: Pydantic response model for query results
        id_getter: Function to extract ID from row for sorting/pagination
        resource_name: Singular resource name (e.g., "model", "deck", "card")
        resource_plural: Plural resource name (e.g., "models", "decks", "cards")
        tag: OpenAPI tag for grouping (e.g., "Models", "Decks", "Cards")
        permission_resource: Queries need read:<this>, mutations write:<this>
            (shared/permissions.py)
        description: Brief description of the resource (included in operation descriptions)
        post_path: Optional custom path for POST query endpoint (default: path + "/query")

    Returns:
        Single APIRouter with all endpoints registered:
        - GET {path} - Query with URL params
        - POST {path}/query - Query with body params
        - POST {path} - Create (if mutations.create provided)
        - PATCH {path}/{id} - Partial update (if mutations.patch provided)
        - DELETE {path}/{id} - Delete (if mutations.delete provided)
        - Subresource operations (if mutations.subresources provided)

    Example:
        router = create_resource_routes(
            path="/v1/models",
            caps=SourceCaps(...),
            response_model=Paginated[ModelRow],
            id_getter=make_id_getter("id"),
            resource_name="model",
            resource_plural="models",
            tag="Models",
            permission_resource="models",
            description="Note types define the structure of cards in Anki."
        )
        app.include_router(router)
    """
    router = APIRouter()

    # Determine POST path
    if post_path is None:
        post_path = f"{path}/query"

    # Capitalize for operation IDs
    resource_name_title = resource_name.title()
    resource_plural_title = resource_plural.title()
    read_permission = requires(f"read:{permission_resource}")
    write_permission = requires(f"write:{permission_resource}")

    def query_response(page):
        # The shared query engine already validated this envelope. Preserve
        # custom response models through FastAPI's normal validation path.
        if response_model is Paginated[ModelRow] and type(page) is response_model:
            return Response(render_query_page(page), media_type="application/json")
        return page

    # GET endpoint - query params in URL
    @router.get(
        path,
        response_model=response_model,
        response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
        summary=f"List {resource_plural}",
        description=f"Query {resource_plural} with filtering, field selection, and pagination. {description}",
        tags=[tag],
        operation_id=f"list{resource_plural_title}",
        openapi_extra=read_permission,
    )
    def _get(
        select: Optional[str] = Query(default=None, description=(
            "Comma-separated fields to return, e.g. `id,name`. Arrays: `fields[]` returns every "
            "element, `fields[].name` one property of each, `fields[].(name,value)` several, and "
            "`fields[name in [\"Front\",\"Back\"]]` only the elements whose `name` is listed.")),
        where: Optional[List[str]] = Query(default=None, description="Filter clauses (can specify multiple)"),
        search: Optional[str] = Query(default=None, description="Anki search string (e.g. 'deck:Japanese tag:verb'). Only supported by search-backed resources; others return 400."),
        order: Optional[str] = Query(default=None, description=(
            "Sort: a name, optionally with :asc (default) or :desc, e.g. due:desc. Cards and notes "
            "use Anki's Browser sorts (due, interval, ease, lapses, reviews, created, card_modified, "
            "note_modified, deck, note_type, sort_field, tags, position, card_type; difficulty, "
            "stability and retrievability on cards); other resources a field of their rows. Ties "
            "in ascending id. Without it, rows come in ascending id.")),
        shape: Literal["object", "scalar"] = Query(default="object", description=(
            "object (default): each item is an object with the selected fields. scalar: with "
            "exactly one selected field, each item is that field's bare value.")),
        limit: Optional[int] = Query(default=None, ge=1, description="Maximum results in this response. Omit to return all matches; no fixed upper cap."),
        cursor: Optional[str] = Query(default=None, description="Opaque next_cursor from the previous response. Omit to start at page one; malformed or empty cursors return 400."),
    ) -> Any:
        """Query resource collection with URL parameters."""
        # Keyword args: _execute_query's positional order must never be
        # assumed here - a silent shift would land `shape` in `search`.
        return query_response(_execute_query(
            select=select, where=where, search=search, shape=shape, order=order,
            limit=limit, cursor=cursor, caps=caps, id_getter=id_getter,
        ))

    # POST endpoint - query params in body
    @router.post(
        post_path,
        response_model=response_model,
        response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
        summary=f"Query {resource_plural} (POST)",
        description=f"Query {resource_plural} using request body. Supports complex queries with filtering and field selection. Omit cursor or use null to start at page one; malformed or empty cursors return 400.",
        tags=[tag],
        operation_id=f"query{resource_plural_title}",
        openapi_extra=read_permission,
    )
    def _post_query(
        query: QueryRequest = Body(..., description="Query parameters in request body"),
    ) -> Any:
        """Query resource collection with POST body parameters."""
        return query_response(_execute_query(
            select=query.select,
            where=query.where,
            search=query.search,
            shape=query.shape,
            order=query.order,
            limit=query.limit,
            cursor=query.cursor,
            caps=caps,
            id_getter=id_getter,
        ))

    # Mutation endpoints (if mutations provided)
    if caps.mutations:
        # POST {path} - Create
        if caps.mutations.create:
            @router.post(
                path,
                response_model=MutationResult[Any],
                response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
                status_code=201,
                summary=f"Create {resource_name}",
                description=f"Create a new {resource_name}. {description}",
                tags=[tag],
                operation_id=f"create{resource_name_title}",
                openapi_extra=write_permission,
            )
            @handle_mutation_errors("create")
            def _create(
                data: Dict[str, Any] = Body(..., description=f"{resource_name_title} data to create"),
            ) -> MutationResult[Any]:
                """Create a new resource."""
                with track_operation("create") as stats:
                    result = caps.mutations.create(data)
                    return MutationResult(result=_plain(result), stats=stats)

        # PATCH {path}/{id} - Partial update
        if caps.mutations.patch:
            @router.patch(
                f"{path}/{{id}}",
                response_model=MutationResult[Any],
                response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
                summary=f"Update {resource_name}",
                description=f"Partially update a {resource_name}. Only provided fields will be updated.",
                tags=[tag],
                operation_id=f"update{resource_name_title}",
                openapi_extra=write_permission,
            )
            @handle_mutation_errors("update")
            def _patch(
                id: int = Path(..., description=f"{resource_name_title} ID"),
                updates: Dict[str, Any] = Body(..., description="Fields to update"),
            ) -> MutationResult[Any]:
                """Partially update a resource."""
                with track_operation("patch") as stats:
                    result = caps.mutations.patch(id, updates)
                    if result is None:
                        raise HTTPException(status_code=404, detail=f"{resource_name_title} with id={id} not found")
                    return MutationResult(result=_plain(result), stats=stats)

        # DELETE {path}/{id} - Delete
        if caps.mutations.delete:
            @router.delete(
                f"{path}/{{id}}",
                response_model=DeletionResult,
                summary=f"Delete {resource_name}",
                description=f"Delete a {resource_name}.",
                tags=[tag],
                operation_id=f"delete{resource_name_title}",
                openapi_extra=write_permission,
            )
            @handle_mutation_errors("delete")
            def _delete(
                id: int = Path(..., description=f"{resource_name_title} ID to delete"),
            ) -> DeletionResult:
                """Delete a resource."""
                with track_operation("delete") as stats:
                    success = caps.mutations.delete(id)
                    if not success:
                        raise HTTPException(status_code=404, detail=f"{resource_name_title} with id={id} not found")
                    return DeletionResult(success=True, affected_ids=[id], stats=stats)

        # Subresource routes - pass parent tag to keep all operations under same tag
        for subres_name, subres_caps in caps.mutations.subresources.items():
            _add_subresource_routes(router, path, resource_name, subres_name, subres_caps, response_model=Any, parent_tag=tag,
                                    openapi_extra=write_permission)

    return router


def _add_subresource_routes(
    router: APIRouter,
    parent_path: str,
    parent_resource_name: str,
    subres_name: str,
    caps: Any,  # SubresourceMutations
    response_model: Any,
    parent_tag: str,
    openapi_extra: Dict[str, Any],
):
    """
    Add routes for a subresource (fields, templates, etc.)

    This function uses a dynamic handler creation pattern with inspect.Signature
    manipulation to achieve semantic path parameter naming in FastAPI.

    WHY THIS PATTERN EXISTS:
    FastAPI matches path parameters by name. For semantic URLs like:
        /v1/models/{model_id}/fields/{field_id}

    We want the handler to receive parameters named 'model_id' and 'field_id'
    (not generic names like 'parent_id' and 'sub_id').

    The problem: We can't know the exact parameter names at code-writing time
    because this function is generic and handles multiple subresource types
    (fields, templates, etc.) under different parent resources.

    THE SOLUTION:
    1. Create handler functions dynamically with **kwargs
    2. Use inspect.Signature to inject proper parameter names and type hints
    3. FastAPI reads the signature and matches path params correctly

    ALTERNATIVE APPROACHES CONSIDERED:
    - FastAPI Depends(): Doesn't support dynamic path parameter names
    - Class-based views: Adds complexity, doesn't solve the core issue
    - Generic parameter names: Loses semantic meaning in API docs

    TRADEOFFS:
    ✓ Pros: Semantic URLs, good API docs, consistent naming conventions
    ✗ Cons: Complex code, harder to debug, limited IDE autocomplete

    All subresource operations use the parent resource's tag for unified grouping.
    """
    path_name = caps.path_name or subres_name

    # Path-param type for the sub-resource identifier, per the spec's id_type
    sub_id_annotation = int if getattr(caps, "id_type", "str") == "int" else str

    # Create semantic parameter names (e.g., "model_id", "field_id")
    parent_id_param = f"{parent_resource_name}_id"
    # Remove trailing 's' for singular subresource name (fields -> field, templates -> template)
    sub_resource_singular = subres_name.rstrip('s') if subres_name.endswith('s') else subres_name
    sub_id_param = f"{sub_resource_singular}_id"

    # Build paths with semantic names
    base_path = f"{parent_path}/{{{parent_id_param}}}/{path_name}"
    item_path = f"{base_path}/{{{sub_id_param}:path}}"

    # Capitalize for operation IDs and summaries
    sub_resource_singular_title = sub_resource_singular.title()
    subres_name_title = subres_name.title()

    # POST - Create subresource item
    if caps.create:
        # Create wrapper to rename parameters dynamically
        def make_create_handler(parent_param_name: str):
            @handle_mutation_errors(f"create_{subres_name}")
            def handler(**kwargs):
                parent_id = kwargs.get(parent_param_name)
                data = kwargs.get('data')
                with track_operation(f"create_{subres_name}") as stats:
                    result = caps.create(parent_id, data)
                    return MutationResult(result=_plain(result), stats=stats)

            # Set proper signature for FastAPI
            import inspect
            handler.__signature__ = inspect.Signature([
                inspect.Parameter(parent_param_name, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=int, default=Path(..., description=f"{parent_resource_name.title()} ID")),
                inspect.Parameter('data', inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=Dict[str, Any], default=Body(..., description="Subresource data"))
            ])
            return handler

        router.add_api_route(
            base_path,
            make_create_handler(parent_id_param),
            methods=["POST"],
            response_model=MutationResult[response_model],
            response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
            status_code=201,
            summary=f"Create {sub_resource_singular}",
            description=f"Add a new {sub_resource_singular} to the {parent_resource_name}",
            tags=[parent_tag],
            operation_id=f"create{sub_resource_singular_title}",
            openapi_extra=openapi_extra,
        )

    # PATCH - Update subresource item
    if caps.patch:
        def make_patch_handler(parent_param_name: str, sub_param_name: str):
            @handle_mutation_errors(f"update_{subres_name}")
            def handler(**kwargs):
                parent_id = kwargs.get(parent_param_name)
                sub_id = kwargs.get(sub_param_name)
                updates = kwargs.get('updates')
                with track_operation(f"patch_{subres_name}") as stats:
                    result = caps.patch(parent_id, sub_id, updates)
                    return MutationResult(result=_plain(result), stats=stats)

            import inspect
            handler.__signature__ = inspect.Signature([
                inspect.Parameter(parent_param_name, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=int, default=Path(..., description=f"{parent_resource_name.title()} ID")),
                inspect.Parameter(sub_param_name, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=sub_id_annotation, default=Path(..., description=f"{sub_resource_singular.title()} identifier")),
                inspect.Parameter('updates', inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=Dict[str, Any], default=Body(..., description="Fields to update"))
            ])
            return handler

        router.add_api_route(
            item_path,
            make_patch_handler(parent_id_param, sub_id_param),
            methods=["PATCH"],
            response_model=MutationResult[response_model],
            response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
            summary=f"Update {sub_resource_singular}",
            description=f"Update properties of a {sub_resource_singular} in the {parent_resource_name}",
            tags=[parent_tag],
            operation_id=f"update{sub_resource_singular_title}",
            openapi_extra=openapi_extra,
        )

    # DELETE - Remove subresource item
    if caps.delete:
        def make_delete_handler(parent_param_name: str, sub_param_name: str):
            @handle_mutation_errors(f"delete_{subres_name}")
            def handler(**kwargs):
                parent_id = kwargs.get(parent_param_name)
                sub_id = kwargs.get(sub_param_name)
                with track_operation(f"delete_{subres_name}") as stats:
                    result = caps.delete(parent_id, sub_id)
                    return MutationResult(result=_plain(result), stats=stats)

            import inspect
            handler.__signature__ = inspect.Signature([
                inspect.Parameter(parent_param_name, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=int, default=Path(..., description=f"{parent_resource_name.title()} ID")),
                inspect.Parameter(sub_param_name, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=sub_id_annotation, default=Path(..., description=f"{sub_resource_singular.title()} identifier"))
            ])
            return handler

        router.add_api_route(
            item_path,
            make_delete_handler(parent_id_param, sub_id_param),
            methods=["DELETE"],
            response_model=MutationResult[response_model],
            response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
            summary=f"Delete {sub_resource_singular}",
            description=f"Remove a {sub_resource_singular} from the {parent_resource_name}",
            tags=[parent_tag],
            operation_id=f"delete{sub_resource_singular_title}",
            openapi_extra=openapi_extra,
        )

    # PUT :order - Reorder subresource items
    if caps.reorder:
        def make_reorder_handler(parent_param_name: str):
            @handle_mutation_errors(f"reorder_{subres_name}")
            def handler(**kwargs):
                parent_id = kwargs.get(parent_param_name)
                body = kwargs.get('body')
                with track_operation(f"reorder_{subres_name}") as stats:
                    order = body.get("order", [])
                    if not order:
                        raise ValueError("'order' array is required")
                    result = caps.reorder(parent_id, order)
                    return MutationResult(result=_plain(result), stats=stats)

            import inspect
            handler.__signature__ = inspect.Signature([
                inspect.Parameter(parent_param_name, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=int, default=Path(..., description=f"{parent_resource_name.title()} ID")),
                inspect.Parameter('body', inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=Dict[str, List[Any]], default=Body(..., description="Order specification"))
            ])
            return handler

        router.add_api_route(
            f"{base_path}:order",
            make_reorder_handler(parent_id_param),
            methods=["PUT"],
            response_model=MutationResult[response_model],
            response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
            summary=f"Reorder {subres_name}",
            description=f"Change the order of {subres_name} in the {parent_resource_name}",
            tags=[parent_tag],
            operation_id=f"reorder{subres_name_title}",
            openapi_extra=openapi_extra,
        )

def make_id_getter(id_key: str = "id"):
    def _get(r):
        if isinstance(r, dict):
            v = r.get(id_key, None)
        else:
            v = getattr(r, id_key, None)
        if v is None:
            # Explain exactly which keys were present
            keys = list(r.keys()) if isinstance(r, dict) else [a for a in dir(r) if not a.startswith("_")]
            raise HTTPException(
                status_code=400,
                detail=f"Row missing required '{id_key}' for sorting/pagination. Available keys: {keys}"
            )
        try:
            return int(v)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Field '{id_key}' not int-coercible: {v!r}"
            ) from None
    return _get
