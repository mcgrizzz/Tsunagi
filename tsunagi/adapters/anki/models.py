from typing import Any, List, Mapping
from aqt import mw

from ..ops import on_main
from ...shared.schemas.models import ModelInfo

@on_main
def list_models() -> List[ModelInfo]:
    return [ModelInfo.model_validate(m) for m in mw.col.models.all()]

@on_main
def get_models_by_ids(ids: List[int]) -> List[ModelInfo]:
    mm = mw.col.models
    out: List[ModelInfo] = []
    for mid in ids:
        m = mm.get(mid)
        if m:
            out.append(ModelInfo.model_validate(m))
    return out

@on_main
def get_model_names_and_ids() -> List[Mapping[str, Any]]:
    res: List[Mapping[str, Any]] = []
    for nt in mw.col.models.all_names_and_ids():
        # nt.id is NotetypeId -> int() is fine
        res.append({"id": int(nt.id), "name": nt.name})
    return res