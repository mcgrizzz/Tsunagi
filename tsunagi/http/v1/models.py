# tsunagi/http/v1/models.py
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Union
from ...shared.schemas.wrappers import Paginated, ProjectedObject, Scalar
from ...shared.schemas.models import ModelInfo
from ...adapters.anki.models import list_models
from ...shared.pagination import paginate_keyset
from ...shared.selecting import parse_select_csv, maybe_flatten, project_scalars

router = APIRouter()

ModelRow = Union[ ModelInfo, ProjectedObject, Scalar]

@router.get("/v1/models", response_model=Paginated[ModelRow])
def get_models(
    select: Optional[str] = Query(default=None, description="top-level keys: id,name,fields,templates"),
    shape: Optional[str]  = Query(default="auto", description="auto|object|scalar"),
    limit: int            = Query(default=1000, ge=1, le=5000),
    cursor: Optional[str] = None,
) -> Paginated[ModelRow]:
    try:
        all_items: List[ModelInfo] = list_models()

        all_items.sort(key=lambda m: int(m.id)) # anki service doesn't sort on id
        page_items, next_cursor = paginate_keyset(all_items, limit, cursor, key_fn=lambda m: int(m.id))

        # No select → return full objects (ProjectedObject)
        if select in (None, ""):
            return Paginated[ModelRow](items=page_items, next_cursor=next_cursor)

        # Select present → project then maybe flatten
        nodes = parse_select_csv(select)
        #validate_select(nodes, _ALLOWED)

        projected_objs = [project_scalars(d.model_dump(), nodes) for d in page_items]
        final_items: List[ModelRow] = maybe_flatten(projected_objs, nodes, shape or "auto")

        # final_items is either List[ProjectedObject] or List[Scalar]
        return Paginated[ModelRow](items=final_items, next_cursor=next_cursor)

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load models: {e}")
