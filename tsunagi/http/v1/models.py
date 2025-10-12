# tsunagi/http/v1/models.py
from fastapi import HTTPException, Query
from typing import Optional, List
import time

from ...shared.route_factory import ModelRow, create_get_route, make_id_getter
from ...shared.planning import IndexSpec, SourceCaps
from ...shared.schemas.wrappers import Paginated
from ...adapters.anki.models import get_model_names_and_ids, get_models_by_ids, list_models

caps = SourceCaps(
    fetch_all = list_models,
    indices=[
        IndexSpec(path=("id",), fetch_values=get_models_by_ids),
    ],
    columns_fetchers={
        frozenset({"id", "name"}): get_model_names_and_ids,
    }, 
)

router = create_get_route(
    path="/v1/models",
    caps=caps,
    response_model=Paginated[ModelRow],
    id_getter=make_id_getter("id"),
)
