"""
Collection- and profile-level routes.

Hand-written for the same reason as tags and media: these are commands against
the running application, not a resource with rows to plan a query over. They
follow the `resource:verb` convention already used by /v1/cards:suspend and
/v1/models:find-replace.
"""
import time

from fastapi import APIRouter, Body

from ...adapters.anki.collection import (
    active_profile,
    check_database,
    collection_meta,
    export_package,
    import_package,
    list_profiles,
    load_profile,
    reload_collection,
    sync_collection,
)
from ...shared.errors import handle_mutation_errors
from ...shared.schemas.collection import (
    CollectionActionResult,
    CollectionMeta,
    ExportRequest,
    ImportRequest,
    ImportResult,
    ProfileList,
    ProfileLoad,
    ProfileLoadResult,
    SyncResult,
)

router = APIRouter()


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


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
        "Closes the current profile and opens another. The collection is "
        "unavailable while Anki switches, so requests in that window get a 503 "
        "rather than a half-open collection. `loaded` is false when there is no "
        "profile by that name."
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


@router.post(
    "/v1/collection:import",
    response_model=ImportResult,
    summary="Import a package",
    description=(
        "Merges an .apkg into the current collection. The path is resolved on "
        "the machine running Anki."
    ),
    tags=["Collection"],
    operation_id="importPackage",
)
@handle_mutation_errors("import")
def import_(body: ImportRequest = Body(...)) -> ImportResult:
    start = time.perf_counter()
    out = import_package(body.path)
    return ImportResult(imported=out["imported"], updated=out["updated"],
                        stats=_stats(start))


@router.post(
    "/v1/collection:reload",
    response_model=CollectionActionResult,
    summary="Reload the collection",
    description="Drops Anki's cached state so the next read sees what is on disk.",
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
