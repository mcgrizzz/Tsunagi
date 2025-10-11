from typing import Any, Dict, List, Optional

from ...shared.schemas.models import ModelInfo
from ...adapters.anki.models import get_models_by_ids

def ac_findModelsById(params: Dict[str, Any]) -> List[Optional[ModelInfo]]:
    ids = params.get("modelIds") or params.get("ids") or []
    if not isinstance(ids, list):
        raise ValueError("modelIds must be an array of integers")
    return get_models_by_ids([int(x) for x in ids])  # returns List[Optional[ModelInfo]]