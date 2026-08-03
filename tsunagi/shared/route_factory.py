from __future__ import annotations

import time
import traceback
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel

from ..shared.pagination import decode_cursor, encode_cursor, paginate_keyset
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
from .planning import SourceCaps, make_plan
from .selecting import (
    maybe_flatten,
    parse_select_csv,
    project_scalars,
    referenced_top_fields,
)

Row = Union[Mapping[str, Any], Any]
ModelRow = Union[Any, ProjectedObject, Scalar]

def _stats(start_time: float) -> dict:
    duration_ms = (time.perf_counter() - start_time) * 1000.0
    return {"duration_ms": round(duration_ms, 3)}

def _plain(x: Any) -> Any:
    # Serialize schema rows to human field names ourselves. FastAPI's
    # _prepare_response_content calls .dict(by_alias=True) on BaseModels
    # BEFORE response validation, so response_model_by_alias=False never
    # reaches rows typed as Any - Anki wire aliases would leak through.
    return x.dict() if isinstance(x, BaseModel) else x

def _as_dict(x: Any) -> Mapping[str, Any]:
    # Use the schema's human-readable field names (fields, templates,
    # sort_field) as the canonical keys for select/where. Aliases (flds,
    # tmpls, ...) remain available via `select` aliasing if a caller wants
    # Anki's wire names. This matches the non-aliased response output.
    return x if isinstance(x, Mapping) else x.dict()

def _finish(
    page_rows: List[Row],
    next_cursor: Optional[str],
    select: Optional[str],
    shape: Optional[str],
    start: float,
) -> Paginated[ModelRow]:
    """Project (if select) and wrap a page. Shared by all planner tiers."""
    if not select:
        return Paginated[ModelRow](items=[_plain(r) for r in page_rows],
                                   next_cursor=next_cursor, stats=_stats(start))
    nodes = parse_select_csv(select)
    projected = [project_scalars(_as_dict(r), nodes) for r in page_rows]
    final_items: List[ModelRow] = maybe_flatten(projected, nodes, shape or "auto")
    return Paginated[ModelRow](items=final_items, next_cursor=next_cursor, stats=_stats(start))

def _paged_scan(
    plan: Any,
    limit: int,
    cursor: Optional[str],
    wants: Optional[set],
    id_getter: Callable[[Row], int],
    pred: Optional[Callable[[Mapping[str, Any]], bool]],
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
    ids = sorted({int(i) for i in plan.find_ids()})
    last_key = decode_cursor(cursor).get("last_key")
    if last_key is not None:
        ids = [i for i in ids if i > last_key]

    if pred is None:
        # No filtering: one batch is exactly the page.
        page_ids, more = ids[:limit], len(ids) > limit
        rows = plan.hydrate(page_ids, wants) if page_ids else []
        return rows, (encode_cursor({"last_key": page_ids[-1]}) if more and page_ids else None)

    batch_size = max(limit, 50)
    out: List[Row] = []
    examined = 0

    while examined < len(ids) and len(out) < limit:
        chunk = ids[examined:examined + batch_size]
        examined += len(chunk)
        out.extend(r for r in plan.hydrate(chunk, wants) if pred(_as_dict(r)))

    if len(out) > limit:
        # Over-collected within a batch: cut to the page and resume from the
        # last INCLUDED row, so the surplus isn't skipped next time.
        out = out[:limit]
        return out, encode_cursor({"last_key": id_getter(out[-1])})
    if examined < len(ids):
        return out, encode_cursor({"last_key": ids[examined - 1]})
    return out, None

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
    limit: int,
    cursor: Optional[str],
    caps: SourceCaps,
    id_getter: Callable[[Row], int],
    search: Optional[str] = None,
) -> Paginated[ModelRow]:
    """
    Core query execution logic shared between GET and POST routes.
    """
    start = time.perf_counter()
    try:
        plan = make_plan(select, where, caps, search)
        wants = _wanted_fields(select, where)

        if plan.find_ids is not None:
            page_rows, next_cursor = _paged_scan(
                plan, limit, cursor, wants, id_getter,
                build_predicate(where) if where else None,
            )
            return _finish(page_rows, next_cursor, select, shape, start)

        rows = plan.fetch(wants) if plan.mode == "index" else plan.fetch()

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
        print("[tsunagi] query failed:\n" + traceback.format_exc())
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

    # GET endpoint - query params in URL
    @router.get(
        path,
        response_model=response_model,
        response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
        summary=f"List {resource_plural}",
        description=f"Query {resource_plural} with filtering, field selection, and pagination. {description}",
        tags=[tag],
        operation_id=f"list{resource_plural_title}"
    )
    def _get(
        select: Optional[str] = Query(default=None, description="Comma-separated fields to return"),
        where: Optional[List[str]] = Query(default=None, description="Filter clauses (can specify multiple)"),
        search: Optional[str] = Query(default=None, description="Anki search string (e.g. 'deck:Japanese tag:verb'). Only supported by search-backed resources; others return 400."),
        shape: Optional[str]  = Query(default="auto", description="Response shape: auto, object, or scalar"),
        limit: int            = Query(default=1000, ge=1, le=5000, description="Maximum number of results"),
        cursor: Optional[str] = Query(default=None, description="Pagination cursor from previous response"),
    ) -> Any:
        """Query resource collection with URL parameters."""
        # Keyword args: _execute_query's positional order must never be
        # assumed here - a silent shift would land `shape` in `search`.
        return _execute_query(
            select=select, where=where, search=search, shape=shape,
            limit=limit, cursor=cursor, caps=caps, id_getter=id_getter,
        )

    # POST endpoint - query params in body
    @router.post(
        post_path,
        response_model=response_model,
        response_model_by_alias=False,  # emit human-readable field names, not Anki aliases
        summary=f"Query {resource_plural} (POST)",
        description=f"Query {resource_plural} using request body. Supports complex queries with filtering and field selection.",
        tags=[tag],
        operation_id=f"query{resource_plural_title}"
    )
    def _post_query(
        query: QueryRequest = Body(..., description="Query parameters in request body"),
    ) -> Any:
        """Query resource collection with POST body parameters."""
        return _execute_query(
            select=query.select,
            where=query.where,
            search=query.search,
            shape=query.shape,
            limit=query.limit,
            cursor=query.cursor,
            caps=caps,
            id_getter=id_getter,
        )

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
                operation_id=f"create{resource_name_title}"
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
                operation_id=f"update{resource_name_title}"
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
                operation_id=f"delete{resource_name_title}"
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
            _add_subresource_routes(router, path, resource_name, subres_name, subres_caps, response_model=Any, parent_tag=tag)

    return router


def _add_subresource_routes(
    router: APIRouter,
    parent_path: str,
    parent_resource_name: str,
    subres_name: str,
    caps: Any,  # SubresourceMutations
    response_model: Any,
    parent_tag: str,
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
            operation_id=f"create{sub_resource_singular_title}"
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
            operation_id=f"update{sub_resource_singular_title}"
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
            operation_id=f"delete{sub_resource_singular_title}"
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
            operation_id=f"reorder{subres_name_title}"
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
