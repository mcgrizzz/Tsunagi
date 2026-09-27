"""
Add-ons router - hand-written like tags: a short list keyed by folder name,
nothing for the query planner. Actions are keyed by provider id instead,
which is the same on every install (backlog 2b-P).
"""
import time
from typing import Any, Dict, Optional, Union

from fastapi import APIRouter, Body, HTTPException, Path
from fastapi.responses import JSONResponse

from ...adapters import addon_actions as actions
from ...adapters import providers  # noqa: F401  (registers the bundled providers)
from ...adapters.anki.addons import get_addon, list_addons
from ...adapters.jobs import jobs
from ...shared.errors import handle_mutation_errors
from ...shared.permissions import ADDON, current_caller, denied_message, requires
from ...shared.schemas.addons import (
    ActionInfo,
    ActionList,
    ActionParam,
    ActionResult,
    AddonInfo,
    AddonList,
)
from ...shared.schemas.fsrs import JobSubmitted

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


def _item_info(caller, provider, item, unsupported) -> ActionInfo:
    return ActionInfo(
        name=item.name, title=item.title, description=item.description, level=item.level,
        params={k: ActionParam(**vars(p)) for k, p in item.params.items()},
        shows_ui=item.shows_ui,
        status="unsupported" if unsupported else actions.status(caller, provider, item))


@router.get("/v1/addons/{provider_id}/actions", response_model=ActionList,
            summary="List an add-on's actions",
            description="What a provider offers for its add-on: reads return data, "
                        "other actions run as jobs. `provider_id` is the provider's id "
                        "(`provider` in GET /v1/addons), the same on every install.",
            tags=["Add-ons"], operation_id="listAddonActions",
            openapi_extra=requires("read:addons"))
@handle_mutation_errors("list")
def list_actions(provider_id: str) -> ActionList:
    start = time.perf_counter()
    provider, _ = actions.find(provider_id)
    unsupported = actions.unavailable(provider)
    caller = current_caller.get()
    items = [] if unsupported else provider.items
    return ActionList(provider=provider.id, title=provider.title, unsupported=unsupported,
                      items=[_item_info(caller, provider, i, unsupported) for i in items],
                      stats=_stats(start))


@router.post("/v1/addons/{provider_id}/actions/{name}:run",
             response_model=Union[ActionResult, JobSubmitted],
             responses={202: {"model": JobSubmitted, "description": "The action runs as a job"}},
             summary="Run an add-on action",
             description="The body holds the action's parameters. A read answers 200 with "
                         "its data. Any other action answers 202 with a job; poll "
                         "GET /v1/jobs/{id}. Its result is `{provider, action, result, "
                         "settled, backup}`: `settled` is false if the add-on's follow-up "
                         "work did not end within two minutes, `backup` names the Anki backup "
                         "made before a destructive action. Actions cannot be aborted. Needs "
                         "`addon:<provider>/<name>`, which the user approves in Tsunagi's "
                         "settings; reads need read:addons. 409 if the add-on is unavailable "
                         "or another job is running.",
             tags=["Add-ons"], operation_id="runAddonAction",
             openapi_extra=requires(ADDON))
@handle_mutation_errors("run")
def run_action(provider_id: str, name: str,
               body: Optional[Dict[str, Any]] = Body(None)) -> Union[ActionResult, JSONResponse]:
    start = time.perf_counter()
    provider, item = actions.find(provider_id, name)
    unsupported = actions.unavailable(provider)
    if unsupported:
        raise HTTPException(status_code=409, detail=f"{provider.title} is unavailable: {unsupported}")
    caller = current_caller.get()
    state = actions.status(caller, provider, item)
    if state == "needs_approval":
        raise HTTPException(status_code=403, detail=(
            f"{provider.title}'s action {name!r} is not approved; approve it in Tsunagi's settings"))
    if state == "not_permitted":
        needed = "read:addons" if item.level == "read" else f"{ADDON}:{provider.id}/{name}"
        raise HTTPException(status_code=403, detail=denied_message(caller, needed))
    params = actions.validate(item, body)
    if item.level == "read":
        return ActionResult(result=actions.read(item, params), stats=_stats(start))
    job_id = actions.submit(provider, item, params)
    current = jobs.snapshot(job_id) or {"status": "queued"}
    submitted = JobSubmitted(job_id=job_id, status=current["status"], stats=_stats(start))
    return JSONResponse(status_code=202, content=submitted.dict(),
                        headers={"Location": f"/v1/jobs/{job_id}"})
