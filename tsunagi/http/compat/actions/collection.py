"""
AnkiConnect compatibility handlers for profile and collection actions.

Translations over adapters/anki/collection.py - the same module the
/v1/profiles and /v1/collection:* routes use. Canonical's return shapes are
narrower than the native ones (bare booleans, mostly), so that is what these
hand back.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki.collection import (
    active_profile,
    export_package,
    import_package,
    list_profiles,
    load_profile,
    reload_collection,
    sync_collection,
)
from ..registry import registry


class LoadProfileParams(BaseModel):
    name: str


class ExportPackageParams(BaseModel):
    deck: str
    path: str
    includeSched: bool = False


class ImportPackageParams(BaseModel):
    path: str


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
    """
    Canonical returns False for a missing deck rather than raising, so the
    404 the adapter raises is translated back to that here.
    """
    try:
        return export_package(p.deck, p.path, p.includeSched)
    except Exception as e:
        if type(e).__name__ == "ResourceNotFoundError":
            return False
        raise


@registry.register("importPackage", params=ImportPackageParams)
def ac_importPackage(p: ImportPackageParams) -> bool:
    import_package(p.path)
    return True
