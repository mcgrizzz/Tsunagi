from __future__ import annotations
import time
from typing import Any, Callable, List, Mapping, Optional, Union
from fastapi import APIRouter, HTTPException, Query

from .planning import SourceCaps, make_plan
from .filtering import build_predicate
from .selecting import parse_select_csv, maybe_flatten, project_scalars
from ..shared.pagination import paginate_keyset
from ..shared.schemas.wrappers import Paginated, ProjectedObject, Scalar

Row = Union[Mapping[str, Any], Any]
ModelRow = Union[Any, ProjectedObject, Scalar]

def _stats(start_time: float) -> dict:
    duration_ms = (time.perf_counter() - start_time) * 1000.0
    return {"duration_ms": round(duration_ms, 3)}

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
        start = time.perf_counter()  # start timing
        try:
            plan = make_plan(select, where, caps)
            rows = plan.fetch()

            def as_dict(x: Any) -> Mapping[str, Any]:
                return x if isinstance(x, Mapping) else x.model_dump()

            # We can filter these later in case the user is grabbing by an index, but not worth the effort right now
            if where:
                pred = build_predicate(where)
                rows = [r for r in rows if pred(as_dict(r))]

            rows.sort(key=id_getter)
            page_rows, next_cursor = paginate_keyset(rows, limit, cursor, key_fn=id_getter)

            if not select:
                return Paginated[ModelRow](items=page_rows, next_cursor=next_cursor, stats=_stats(start))

            nodes = parse_select_csv(select)
            projected = [project_scalars(as_dict(r), nodes) for r in page_rows]
            final_items: List[ModelRow] = maybe_flatten(projected, nodes, shape or "auto")
            return Paginated[ModelRow](items=final_items, next_cursor=next_cursor, stats=_stats(start))

        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load: {e}")

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
