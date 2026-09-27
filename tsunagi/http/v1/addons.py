"""
Add-ons router - hand-written like tags: a short list keyed by folder name,
nothing for the query planner. Reading or writing configs needs its own gate:
configs can hold other add-ons' secrets.
"""
import time

from fastapi import APIRouter, Body, Path

from ...adapters.anki.addons import (
    get_addon,
    list_addons,
    read_addon_config,
    write_addon_config,
)
from ...adapters.settings import settings
from ...shared.errors import ValidationError, handle_mutation_errors
from ...shared.schemas.addons import (
    AddonConfig,
    AddonConfigWrite,
    AddonConfigWriteResult,
    AddonInfo,
    AddonList,
)

router = APIRouter()
_ID = Path(..., description="The add-on's folder name, as listed by GET /v1/addons")


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


def _require_gate(name: str, what: str) -> None:
    if not settings.gate_enabled(name):
        raise ValidationError(f"{what} is disabled; " + settings.gate_off_reason(name))


@router.get("/v1/addons", response_model=AddonList, summary="List installed add-ons",
            description="Every installed add-on, enabled or not, sorted by folder name.",
            tags=["Add-ons"], operation_id="listAddons")
@handle_mutation_errors("list")
def list_all() -> AddonList:
    start = time.perf_counter()
    return AddonList(items=list_addons(), stats=_stats(start))


@router.get("/v1/addons/{addon_id}", response_model=AddonInfo, summary="Get an add-on",
            tags=["Add-ons"], operation_id="getAddon")
@handle_mutation_errors("get")
def get_one(addon_id: str = _ID) -> AddonInfo:
    return AddonInfo(**get_addon(addon_id))


@router.get("/v1/addons/{addon_id}/config", response_model=AddonConfig,
            summary="Read an add-on's config",
            description="The config as Anki merges it with the add-on's defaults. Off by "
                        "default: requires the `gates.addons_read_config` gate, because "
                        "configs can hold other add-ons' secrets. Tsunagi's own API key is "
                        "always redacted.",
            tags=["Add-ons"], operation_id="getAddonConfig")
@handle_mutation_errors("read config")
def get_config(addon_id: str = _ID) -> AddonConfig:
    _require_gate("addons_read_config", "reading add-on configs")
    return AddonConfig(id=addon_id, config=read_addon_config(addon_id))


@router.put("/v1/addons/{addon_id}/config", response_model=AddonConfigWriteResult,
            summary="Replace an add-on's config",
            description="Saves the whole config the way Anki's config editor does: checked "
                        "against the add-on's config.schema.json, written only if changed, "
                        "then the add-on's config-updated hook runs. Off by default: requires "
                        "the `gates.addons_write_config` gate. Tsunagi's own config cannot be "
                        "changed here.",
            tags=["Add-ons"], operation_id="putAddonConfig")
@handle_mutation_errors("write config")
def put_config(addon_id: str = _ID, body: AddonConfigWrite = Body(...)) -> AddonConfigWriteResult:
    _require_gate("addons_write_config", "writing add-on configs")
    start = time.perf_counter()
    changed = write_addon_config(addon_id, body.config)
    return AddonConfigWriteResult(id=addon_id, changed=changed, stats=_stats(start))
