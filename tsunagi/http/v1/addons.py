"""
Add-ons router - hand-written like tags: a short list keyed by folder name,
nothing for the query planner.
"""
import time

from fastapi import APIRouter, Path

from ...adapters.anki.addons import get_addon, list_addons
from ...shared.errors import handle_mutation_errors
from ...shared.permissions import requires
from ...shared.schemas.addons import AddonInfo, AddonList

router = APIRouter()
_ID = Path(..., description="The add-on's folder name, as listed by GET /v1/addons")


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


@router.get("/v1/addons", response_model=AddonList, summary="List installed add-ons",
            description="Every installed add-on, enabled or not, sorted by folder name.",
            tags=["Add-ons"], operation_id="listAddons",
            openapi_extra=requires("read:addons"))
@handle_mutation_errors("list")
def list_all() -> AddonList:
    start = time.perf_counter()
    return AddonList(items=list_addons(), stats=_stats(start))


@router.get("/v1/addons/{addon_id}", response_model=AddonInfo, summary="Get an add-on",
            tags=["Add-ons"], operation_id="getAddon",
            openapi_extra=requires("read:addons"))
@handle_mutation_errors("get")
def get_one(addon_id: str = _ID) -> AddonInfo:
    return AddonInfo(**get_addon(addon_id))
