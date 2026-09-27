"""
Installed add-ons and their config, through Anki's AddonManager.

Everything runs on the main thread: the manager is GUI state, and an add-on's
config-updated hook expects to be called where Anki's own editor calls it.
Enabling, disabling and deleting add-ons stay out of scope (they need a
restart and Anki's own prompts).
"""
from typing import Any, Dict, List, Optional

from ...shared.errors import ResourceNotFoundError, ValidationError
from ..config import ADDON_PACKAGE
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


def read_addon_config(addon_id: str) -> Optional[Dict[str, Any]]:
    """The config as Anki merges it; None when the add-on has none."""
    def _read() -> Optional[Dict[str, Any]]:
        mgr = _manager()
        _require(mgr, addon_id)
        config = mgr.getConfig(addon_id)
        if config is not None and addon_id == ADDON_PACKAGE and config.get("api_key"):
            config = {**config, "api_key": "<redacted>"}
        return config
    return call_on_main(_read)


def write_addon_config(addon_id: str, config: Any) -> bool:
    """
    Save a whole config the way Anki's config editor does: validate against the
    add-on's config.schema.json, write only if changed, then call its
    config-updated hook. Returns whether anything changed.
    """
    if addon_id == ADDON_PACKAGE:
        # It holds the API key, allowlist and gates; changing them over the API
        # would let any client unlock itself.
        raise ValidationError("Tsunagi's own settings can only be changed in its settings dialog")
    if not isinstance(config, dict):
        raise ValidationError("config must be a JSON object")

    def _write() -> bool:
        import jsonschema

        mgr = _manager()
        _require(mgr, addon_id)
        current = mgr.getConfig(addon_id)
        if current is None:
            raise ValidationError(f"add-on {addon_id} has no config")
        try:
            jsonschema.validate(config, mgr._addon_schema(addon_id))
        except jsonschema.exceptions.ValidationError as e:
            path = "/".join(str(p) for p in e.path)
            raise ValidationError(
                f"config rejected by the add-on's schema at '{path}': {e.message}") from e
        if config == current:
            return False
        mgr.writeConfig(addon_id, config)
        updated = mgr.configUpdatedAction(addon_id)
        if updated:
            updated(config)
        return True
    return call_on_main(_write)
