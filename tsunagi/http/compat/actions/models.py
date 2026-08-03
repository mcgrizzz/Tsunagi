"""
AnkiConnect compatibility handlers for model (note type) actions.

Wire shapes and error strings mirror AnkiConnect exactly (clients
string-match); full models are serialized with by_alias=True so keys match
Anki's schema11 names (flds, tmpls, sortf, ...).
"""
from typing import Any, Dict, List

from pydantic import BaseModel

from ....adapters.anki.models import (
    get_model_names_and_ids,
    get_models_by_names,
    get_raw_models,
)
from ..errors import MODEL_NOT_FOUND
from ..registry import registry


class ModelFieldNamesParams(BaseModel):
    modelName: str


class FindModelsByNameParams(BaseModel):
    modelNames: List[str]


class FindModelsByIdParams(BaseModel):
    modelIds: List[int]


@registry.register("modelNames")
def ac_modelNames(params: Dict[str, Any]) -> List[str]:
    return [d["name"] for d in get_model_names_and_ids()]


@registry.register("modelNamesAndIds")
def ac_modelNamesAndIds(params: Dict[str, Any]) -> Dict[str, int]:
    return {d["name"]: d["id"] for d in get_model_names_and_ids()}


@registry.register("modelFieldNames", params=ModelFieldNamesParams)
def ac_modelFieldNames(p: ModelFieldNamesParams) -> List[str]:
    models = get_models_by_names([p.modelName])
    if not models:
        raise ValueError(MODEL_NOT_FOUND.format(p.modelName))
    return [f.name for f in models[0].fields]


# findModelsBy* return Anki's raw schema11 dict, exactly as AnkiConnect does.
# Routing them through ModelInfo would silently drop any schema11 key our
# schema doesn't model - the v1 API is where the curated shape belongs.

@registry.register("findModelsByName", params=FindModelsByNameParams)
def ac_findModelsByName(p: FindModelsByNameParams) -> List[Dict[str, Any]]:
    found = get_raw_models(names=p.modelNames)
    out: List[Dict[str, Any]] = []
    for name in p.modelNames:  # input order; raise at FIRST missing (as AnkiConnect)
        m = found.get(name)
        if m is None:
            raise ValueError(MODEL_NOT_FOUND.format(name))
        out.append(m)
    return out


@registry.register("findModelsById", params=FindModelsByIdParams)
def ac_findModelsById(p: FindModelsByIdParams) -> List[Dict[str, Any]]:
    found = get_raw_models(ids=[int(i) for i in p.modelIds])
    out: List[Dict[str, Any]] = []
    for mid in p.modelIds:
        m = found.get(int(mid))
        if m is None:
            raise ValueError(MODEL_NOT_FOUND.format(mid))
        out.append(m)
    return out
