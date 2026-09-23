"""
Collection- and profile-level routes.

Hand-written for the same reason as tags and media: these are commands against
the running application, not a resource with rows to plan a query over. They
follow the `resource:verb` convention already used by /v1/cards:suspend and
/v1/models:find-replace.
"""
import threading
import time
from typing import Union

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from ...adapters import ops
from ...adapters.anki.collection import (
    active_profile,
    check_database,
    collection_capabilities,
    collection_meta,
    export_package,
    import_preferences,
    list_profiles,
    load_profile,
    reload_collection,
    submit_import_package,
    sync_collection,
)
from ...adapters.jobs import jobs
from ...shared.errors import anki_error_detail, handle_mutation_errors
from ...shared.schemas.capabilities import Capabilities, runtime_versions
from ...shared.schemas.collection import (
    CollectionActionResult,
    CollectionMeta,
    ExportRequest,
    ImportPreferences,
    ImportRequest,
    ImportResult,
    ProfileList,
    ProfileLoad,
    ProfileLoadResult,
    SyncResult,
)
from ...shared.schemas.fsrs import JobSubmitted
from ..discovery import native_features, native_operations

router = APIRouter()


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


@router.get(
    "/v1/capabilities",
    response_model=Capabilities,
    summary="Native API capabilities",
    description=(
        "One report for all native operations and collection features. Each has an "
        "effective status: available, disabled in settings, or unsupported by this Anki. "
        "Conditional options carry their own status, reason and setting. Availability "
        "does not bypass input validation, authentication or transient collection/GUI state. "
        "Requires an open collection; /v1/health remains a lightweight liveness check. "
        "AnkiConnect actions are listed separately at /actions."
    ),
    tags=["Collection"],
    operation_id="getCapabilities",
)
@handle_mutation_errors("capabilities")
def capabilities(request: Request) -> Capabilities:
    start = time.perf_counter()
    support = collection_capabilities()
    return Capabilities(versions=runtime_versions(),
                        operations=native_operations(request.app.routes, support),
                        features=native_features(support), stats=_stats(start))


@router.get(
    "/v1/collection",
    response_model=CollectionMeta,
    summary="Collection metadata",
    description=(
        "Collection-wide facts with no row of their own: whether FSRS is "
        "enabled (one switch for the whole collection - per-deck and "
        "per-preset `desired_retention` values exist either way, the "
        "scheduler just ignores them while this is off), and the running "
        "Anki version for feature detection."
    ),
    tags=["Collection"],
    operation_id="getCollectionMeta",
)
@handle_mutation_errors("meta")
def meta() -> CollectionMeta:
    start = time.perf_counter()
    out = collection_meta()
    return CollectionMeta(fsrs=out["fsrs"], anki_version=out["anki_version"],
                          stats=_stats(start))


@router.get(
    "/v1/profiles",
    response_model=ProfileList,
    summary="List profiles",
    description="Every Anki profile, and which one is currently open.",
    tags=["Collection"],
    operation_id="listProfiles",
)
@handle_mutation_errors("list")
def profiles() -> ProfileList:
    start = time.perf_counter()
    return ProfileList(items=list_profiles(), active=active_profile(),
                       stats=_stats(start))


@router.post(
    "/v1/profiles:load",
    response_model=ProfileLoadResult,
    summary="Switch profile",
    description=(
        "Schedules closing the current profile and opening another. `loaded` "
        "confirms acceptance, not completion, and is false for an unknown name. "
        "The server restarts during the switch; requests may encounter 503 or "
        "a connection interruption. Reconnect and GET /v1/profiles to confirm "
        "the active profile."
    ),
    tags=["Collection"],
    operation_id="loadProfile",
)
@handle_mutation_errors("load")
def load(body: ProfileLoad = Body(...)) -> ProfileLoadResult:
    start = time.perf_counter()
    return ProfileLoadResult(loaded=load_profile(body.name), stats=_stats(start))


@router.post(
    "/v1/collection:sync",
    response_model=SyncResult,
    summary="Sync the collection",
    description=(
        "Runs a sync against AnkiWeb using the credentials already configured "
        "in Anki. Errors if no sync account is set up, or if the collection "
        "needs a full upload or download - that requires Anki's own UI."
    ),
    tags=["Collection"],
    operation_id="syncCollection",
)
@handle_mutation_errors("sync")
def sync() -> SyncResult:
    start = time.perf_counter()
    out = sync_collection()
    return SyncResult(status=out["status"],
                      server_message=out["server_message"], stats=_stats(start))


@router.post(
    "/v1/collection:export",
    response_model=CollectionActionResult,
    summary="Export a deck",
    description=(
        "Writes one deck to an .apkg file. The path is resolved on the machine "
        "running Anki, not the caller's."
    ),
    tags=["Collection"],
    operation_id="exportPackage",
)
@handle_mutation_errors("export")
def export(body: ExportRequest = Body(...)) -> CollectionActionResult:
    start = time.perf_counter()
    export_package(body.deck, body.path, body.with_scheduling, body.with_media)
    return CollectionActionResult(stats=_stats(start))


@router.get(
    "/v1/collection/import-options",
    response_model=ImportPreferences,
    summary="Read saved package import options",
    description=(
        "Returns Anki's saved import choices for the open collection. Unsupported "
        "options are listed separately and have null values. Reading does not import "
        "a file or change preferences. Pass explicit options to /v1/collection:import "
        "to keep a reviewed choice fixed even if preferences change before the import."
    ),
    tags=["Collection"],
    operation_id="getImportOptions",
)
@handle_mutation_errors("import-options")
def import_options() -> ImportPreferences:
    start = time.perf_counter()
    return ImportPreferences(**import_preferences(), stats=_stats(start))


@router.post(
    "/v1/collection:import",
    response_model=ImportResult,
    responses={202: {"model": JobSubmitted, "description": "Import still running; poll the job"}},
    summary="Import a package",
    description=(
        "Merges an .apkg into the current collection. The path is resolved on "
        "the machine running Anki. Imports immediately without an options dialog. "
        "Omitted or null options use Anki's saved import preferences, available at "
        "GET /v1/collection/import-options. Explicit values override those choices. "
        "Anki remembers the resulting options after a successful import. "
        "Unsupported explicit options are rejected before importing. Returns the "
        "result with HTTP 200 if the import completes within the operation timeout; "
        "otherwise returns HTTP 202 with a job_id and Location header. Poll "
        "GET /v1/jobs/{job_id}; the same import continues without restarting. "
        "Import jobs cannot be aborted through the API. Only one import or FSRS "
        "job may be active at once (409 otherwise). Jobs are kept in memory only."
    ),
    tags=["Collection"],
    operation_id="importPackage",
)
@handle_mutation_errors("import")
def import_(body: ImportRequest = Body(...)) -> Union[ImportResult, JSONResponse]:
    start = time.perf_counter()
    job = jobs.create("import_package")
    done = threading.Event()
    outcome = {}

    def success(out):
        result = ImportResult(imported=out["imported"], updated=out["updated"],
                              stats=_stats(start))
        outcome["result"] = result
        jobs.finish(job.id, result.dict())
        done.set()

    def failure(exc):
        outcome["error"] = exc
        jobs.fail(job.id, anki_error_detail(exc))
        done.set()

    try:
        submit_import_package(
            body.path, **body.dict(exclude={"path"}, exclude_none=True),
            on_started=lambda: jobs.mark_running(job.id),
            on_success=success, on_failure=failure,
        )
    except Exception as exc:
        failure(exc)

    if done.wait(ops.OP_TIMEOUT):
        if "error" in outcome:
            raise outcome["error"]
        return outcome["result"]

    current = jobs.snapshot(job.id) or {"status": job.status}
    submitted = JobSubmitted(job_id=job.id, status=current["status"], stats=_stats(start))
    return JSONResponse(status_code=202, content=submitted.dict(),
                        headers={"Location": f"/v1/jobs/{job.id}"})


@router.post(
    "/v1/collection:reload",
    response_model=CollectionActionResult,
    summary="Reload the collection (deprecated no-op)",
    description=(
        "This endpoint performs no reload. It remains available for existing clients "
        "and returns success when a collection is open. After a completed collection "
        "operation, query the data directly; no reload step is required. "
        "This request does not clear caches or reopen the collection."
    ),
    deprecated=True,
    tags=["Collection"],
    operation_id="reloadCollection",
)
@handle_mutation_errors("reload")
def reload() -> CollectionActionResult:
    start = time.perf_counter()
    reload_collection()
    return CollectionActionResult(stats=_stats(start))


@router.post(
    "/v1/collection:check-database",
    response_model=CollectionActionResult,
    summary="Check the database",
    description="Runs Anki's Check Database, which rebuilds indexes and fixes inconsistencies.",
    tags=["Collection"],
    operation_id="checkDatabase",
)
@handle_mutation_errors("check")
def check_db() -> CollectionActionResult:
    start = time.perf_counter()
    check_database()
    return CollectionActionResult(stats=_stats(start))
