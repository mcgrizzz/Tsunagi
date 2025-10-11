from typing import List, Optional
from aqt import mw

from ..ops import on_main
from ...shared.schemas.models import ModelInfo, ModelField, ModelTemplate

@on_main
def list_models() -> List[ModelInfo]:
    return [ModelInfo.model_validate(m) for m in mw.col.models.all()]
