"""
Installed add-ons, through Anki's AddonManager (GUI state, read on the main
thread). Settings are not exposed: add-ons offer data and actions through the
provider framework instead. Enabling, disabling and deleting add-ons stay out
of scope (they need a restart and Anki's own prompts).
"""
from typing import Any, Dict, List

from ...shared.errors import ResourceNotFoundError
from ..addon_actions import provider_for_addon
from ..ops import call_on_main


def _manager() -> Any:
    from aqt import mw
    return mw.addonManager


def _require(mgr: Any, addon_id: str) -> None:
    if addon_id not in mgr.allAddons():
        raise ResourceNotFoundError("Add-on", addon_id)


def _info(mgr: Any, meta: Any) -> Dict[str, Any]:
    return {
        "id": meta.dir_name,
        "name": meta.human_name(),
        "ankiweb_id": meta.ankiweb_id(),
        "enabled": bool(meta.enabled),
        "compatible": bool(meta.compatible()),
        "version": meta.human_version,
        "installed_at": int(meta.installed_at or 0),
        "homepage": meta.homepage,
        "has_config": mgr.addonConfigDefaults(meta.dir_name) is not None,
        "has_config_ui": mgr.configAction(meta.dir_name) is not None,
        "provider": provider_for_addon(meta.dir_name),
    }


def list_addons() -> List[Dict[str, Any]]:
    def _read() -> List[Dict[str, Any]]:
        mgr = _manager()
        return [_info(mgr, meta) for meta in sorted(mgr.all_addon_meta(), key=lambda m: m.dir_name)]
    return call_on_main(_read)


def get_addon(addon_id: str) -> Dict[str, Any]:
    def _read() -> Dict[str, Any]:
        mgr = _manager()
        _require(mgr, addon_id)
        return _info(mgr, mgr.addon_meta(addon_id))
    return call_on_main(_read)
