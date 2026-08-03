"""
AnkiConnect compatibility handlers for model (note type) operations.
"""
from typing import Any, Dict, List, Optional

from ...adapters.anki.models import get_models_by_ids
from .registry import registry


@registry.register("findModelsById")
def ac_findModelsById(params: Dict[str, Any]) -> List[Optional[Dict[str, Any]]]:
    """
    Find models by their IDs (AnkiConnect compatible).

    AnkiConnect params:
        modelIds: List[int] - IDs of models to find

    Returns:
        List of model dictionaries (or None for missing models)
    """
    ids = params.get("modelIds") or params.get("ids") or []
    if not isinstance(ids, list):
        raise ValueError("modelIds must be an array of integers")

    models = get_models_by_ids([int(x) for x in ids])

    # Serialize with by_alias=True so keys match AnkiConnect's wire format
    # (flds, tmpls, sortf, ...). The compat layer mirrors AnkiConnect exactly;
    # the v1 API deliberately uses human-readable names instead.
    return [m.dict(by_alias=True) if m else None for m in models]