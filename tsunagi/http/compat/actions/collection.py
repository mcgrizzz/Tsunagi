"""AnkiConnect profile and collection actions.

Profile actions share native adapters. Package actions use Anki's compatibility
APIs to retain the installed version's import/export behavior and raw arguments.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki.collection import (
    active_profile,
    list_profiles,
    load_profile,
    reload_collection,
    sync_collection,
)
from ..registry import registry


class LoadProfileParams(BaseModel):
    name: str


class ExportPackageParams(BaseModel):
    deck: Any = ...
    path: Any = ...
    includeSched: Any = False


class ImportPackageParams(BaseModel):
    path: Any = ...


@registry.register("getProfiles")
def ac_getProfiles(params: Optional[Dict[str, Any]] = None) -> List[str]:
    return list_profiles()


@registry.register("getActiveProfile")
def ac_getActiveProfile(params: Optional[Dict[str, Any]] = None) -> Optional[str]:
    return active_profile()


@registry.register("loadProfile", params=LoadProfileParams)
def ac_loadProfile(p: LoadProfileParams) -> bool:
    return load_profile(p.name)


@registry.register("sync")
def ac_sync(params: Optional[Dict[str, Any]] = None) -> None:
    sync_collection()
    return None


@registry.register("reloadCollection")
def ac_reloadCollection(params: Optional[Dict[str, Any]] = None) -> None:
    reload_collection()
    return None


@registry.register("exportPackage", params=ExportPackageParams)
def ac_exportPackage(p: ExportPackageParams) -> bool:
    from ....adapters.anki.compat import export_package_legacy

    return export_package_legacy(p.deck, p.path, p.includeSched)


@registry.register("importPackage", params=ImportPackageParams)
def ac_importPackage(p: ImportPackageParams) -> bool:
    from ....adapters.anki.compat import import_package_legacy

    return import_package_legacy(p.path)
