from __future__ import annotations
import time
from typing import Any, Callable, List, Mapping, Optional, Union
from fastapi import APIRouter, HTTPException, Query, Body

from .planning import SourceCaps, make_plan
from .filtering import build_predicate
from .selecting import parse_select_csv, maybe_flatten, project_scalars
from ..shared.pagination import paginate_keyset
from ..shared.schemas.wrappers import Paginated, ProjectedObject, QueryRequest, Scalar

Row = Union[Mapping[str, Any], Any]
ModelRow = Union[Any, ProjectedObject, Scalar]

def _stats(start_time: float) -> dict:
    duration_ms = (time.perf_counter() - start_time) * 1000.0
    return {"duration_ms": round(duration_ms, 3)}

def _execute_query(
    select: Optional[str],
    where: Optional[List[str]],
    shape: Optional[str],
    limit: int,
    cursor: Optional[str],
    caps: SourceCaps,
    id_getter: Callable[[Row], int],
) -> Paginated[ModelRow]:
    """
    Core query execution logic shared between GET and POST routes.
    """
    start = time.perf_counter()
    try:
        plan = make_plan(select, where, caps)
        rows = plan.fetch()

        def as_dict(x: Any) -> Mapping[str, Any]:
            return x if isinstance(x, Mapping) else x.model_dump()

        # Filter rows if where clauses provided
        if where:
            pred = build_predicate(where)
            rows = [r for r in rows if pred(as_dict(r))]

        rows.sort(key=id_getter)
        page_rows, next_cursor = paginate_keyset(rows, limit, cursor, key_fn=id_getter)

        # Return without projection if no select
        if not select:
            return Paginated[ModelRow](items=page_rows, next_cursor=next_cursor, stats=_stats(start))

        # Apply field selection and projection
        nodes = parse_select_csv(select)
        projected = [project_scalars(as_dict(r), nodes) for r in page_rows]
        final_items: List[ModelRow] = maybe_flatten(projected, nodes, shape or "auto")
        return Paginated[ModelRow](items=final_items, next_cursor=next_cursor, stats=_stats(start))

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load: {e}")

def create_get_route(
    path: str,
    *,
    caps: SourceCaps,
    response_model: Any,
    id_getter: Callable[[Row], int] = lambda r: int(r["id"] if isinstance(r, Mapping) else r.id),
) -> APIRouter:
    router = APIRouter()

    @router.get(path, response_model=response_model)
    def _get(
        select: Optional[str] = Query(default=None, description="select CSV"),
        where: Optional[List[str]] = Query(default=None, description="repeatable filter clauses"),
        shape: Optional[str]  = Query(default="auto", description="auto|object|scalar"),
        limit: int            = Query(default=1000, ge=1, le=5000),
        cursor: Optional[str] = None,
    ) -> Any:
        return _execute_query(select, where, shape, limit, cursor, caps, id_getter)

    return router

def create_post_query_route(
    path: str,
    *,
    caps: SourceCaps,
    response_model: Any,
    id_getter: Callable[[Row], int] = lambda r: int(r["id"] if isinstance(r, Mapping) else r.id),
) -> APIRouter:
    router = APIRouter()

    @router.post(path, response_model=response_model)
    def _post_query(
        query: QueryRequest = Body(..., description="Query parameters in request body"),
    ) -> Any:
        return _execute_query(
            query.select,
            query.where,
            query.shape,
            query.limit,
            query.cursor,
            caps,
            id_getter,
        )

    return router

def create_query_routes(
    path: str,
    *,
    caps: SourceCaps,
    response_model: Any,
    id_getter: Callable[[Row], int] = lambda r: int(r["id"] if isinstance(r, Mapping) else r.id),
    post_path: Optional[str] = None,
) -> APIRouter:
    """
    Create both GET and POST query routes in a single router.

    Args:
        path: Base path for GET endpoint (e.g., "/v1/models")
        caps: Source capabilities
        response_model: Pydantic response model
        id_getter: Function to extract ID from row for sorting/pagination
        post_path: Optional custom path for POST endpoint (default: path + "/query")

    Returns:
        Single APIRouter with both GET and POST endpoints registered

    Example:
        router = create_query_routes(
            path="/v1/models",
            caps=caps,
            response_model=Paginated[ModelRow],
            id_getter=make_id_getter("id"),
        )
        app.include_router(router)
        # Creates: GET /v1/models and POST /v1/models/query
    """
    router = APIRouter()

    # Determine POST path
    if post_path is None:
        post_path = f"{path}/query"

    # GET endpoint - query params in URL
    @router.get(path, response_model=response_model)
    def _get(
        select: Optional[str] = Query(default=None, description="select CSV"),
        where: Optional[List[str]] = Query(default=None, description="repeatable filter clauses"),
        shape: Optional[str]  = Query(default="auto", description="auto|object|scalar"),
        limit: int            = Query(default=1000, ge=1, le=5000),
        cursor: Optional[str] = None,
    ) -> Any:
        return _execute_query(select, where, shape, limit, cursor, caps, id_getter)

    # POST endpoint - query params in body
    @router.post(post_path, response_model=response_model)
    def _post_query(
        query: QueryRequest = Body(..., description="Query parameters in request body"),
    ) -> Any:
        return _execute_query(
            query.select,
            query.where,
            query.shape,
            query.limit,
            query.cursor,
            caps,
            id_getter,
        )

    return router

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
            )
    return _get
