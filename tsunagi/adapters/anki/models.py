from typing import Any, Dict, List, Mapping, Sequence
from aqt import mw

from ..ops import on_main
from ...shared.schemas.models import ModelInfo

@on_main
def list_models() -> List[ModelInfo]:
    return [ModelInfo.model_validate(m) for m in mw.col.models.all()] # 1 query + 3*each notetype This is worst case since it runs on all notetypes

@on_main
def get_models_by_ids(ids: Sequence[int]) -> List[ModelInfo]: #3*each notetype
    mm = mw.col.models
    out: List[ModelInfo] = []
    for mid in ids:
        m = mm.get(mid)
        if m:
            out.append(ModelInfo.model_validate(m))
    return out

@on_main
def get_models_by_names(names: Sequence[str]) -> List[ModelInfo]: #1 + #3*each notetype
    mm = mw.col.models
    name_to_id: Dict[str, int] = {}
    for nt in mm.all_names_and_ids():
        name_to_id[nt.name] = int(nt.id)

    out: List[ModelInfo] = []
    for name in names:
        if name in name_to_id:
            m = mm.get(name_to_id[name]) # type: ignore
            if m:
                out.append(ModelInfo.model_validate(m))
    return out

@on_main
def get_model_names_and_ids() -> List[Mapping[str, Any]]: #1 query
    res: List[Mapping[str, Any]] = []
    for nt in mw.col.models.all_names_and_ids():
        # nt.id is NotetypeId -> int() is fine
        res.append({"id": int(nt.id), "name": nt.name})
    return res