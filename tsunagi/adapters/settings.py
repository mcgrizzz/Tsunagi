"""
Live, thread-safe view of the addon config.

Middleware and the compat dispatcher read from the module singleton on every
request, so runtime changes (e.g. an origin granted via requestPermission)
take effect immediately. Persistence is an injected callback so this module
stays importable without aqt (tests construct their own Settings).
"""
from __future__ import annotations

import threading
from ipaddress import ip_address
from typing import Any, Callable, Dict, Optional

from .config import ADDON_PACKAGE, DEFAULTS, _migrate

PersistFn = Callable[[Dict[str, Any]], None]

# Gates that read local files or overwrite scheduling data stay off while the
# server listens beyond this computer with no api_key, so another device on
# the network can never use them unauthenticated.
KEY_REQUIRED_GATES = frozenset({"media_allow_local_path", "cards_set_memory_state",
                                "addons_read_config", "addons_write_config"})

def is_loopback_host(host: Any) -> bool:
    """True for a bind address only this computer can reach."""
    host = str(host or "127.0.0.1").strip("[]")
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False  # a hostname: assume other devices can reach it


# Browser-extension origin schemes covered by the "http://localhost" entry
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://", "safari-web-extension://")


class Settings:
    def __init__(self, config: Dict[str, Any], persist: Optional[PersistFn] = None):
        self._lock = threading.Lock()
        self._config = dict(config)
        self._persist = persist
        # Origin of Anki's own web pages (reviewer, editor, add-on pages), set
        # at server start. Card templates run JavaScript there, so a shared
        # deck could otherwise use the API while it is reviewed.
        self.anki_page_origin: Optional[str] = None

    def is_blocked_anki_page(self, origin: Any) -> bool:
        """Anki's own page origin while gates.anki_page_scripts is off."""
        return (origin is not None and origin == self.anki_page_origin
                and not self.gate_enabled("anki_page_scripts"))

    def configure(self, config: Dict[str, Any], persist: Optional[PersistFn]) -> None:
        """
        Replace contents in place (called from start_server). Object identity
        stays stable, so middleware constructed at import time sees live values.
        """
        with self._lock:
            self._config = dict(config)
            self._persist = persist

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._config.get(key, default)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._config)

    def update(self, **changes: Any) -> None:
        """Merge changes into the config and persist the full result."""
        with self._lock:
            self._config.update(changes)
            cfg = dict(self._config)
            persist = self._persist
        if persist:
            persist(cfg)  # writeConfig outside the lock

    def gate_enabled(self, name: str) -> bool:
        """True if the opt-in gate `name` (a key under "gates") is enabled."""
        if name in KEY_REQUIRED_GATES and self._needs_key():
            return False
        return self._gate_switched_on(name)

    def _needs_key(self) -> bool:
        """No api_key while bound to a non-loopback address."""
        return not self.get("api_key") and not is_loopback_host(self.get("host"))

    def _gate_switched_on(self, name: str) -> bool:
        gates = self.get("gates") or {}
        # Anki keeps a saved "gates" dict whole, so gates added later fall back
        # to their defaults.
        return bool(gates.get(name, DEFAULTS["gates"].get(name, False)))

    def gate_off_reason(self, name: str) -> str:
        """What the user must change for a disabled gate to take effect."""
        if self._gate_switched_on(name):
            return (f"gates.{name} needs an API key while Tsunagi accepts connections "
                    "from other devices; set one in Tsunagi's settings")
        return f"enable gates.{name} in Tsunagi's settings"

    def add_cors_origin(self, origin: str) -> None:
        allowlist = list(self.get("cors_allowlist", []))
        if origin in allowlist:
            return
        allowlist.append(origin)
        self.update(cors_allowlist=allowlist)

    def is_origin_allowed(self, origin: str) -> bool:
        """
        Mirrors AnkiConnect's allowOrigin: "*" allows everything, exact
        matches win, and the "http://localhost" entry additionally allows
        127.0.0.1 origins and browser extensions (this is why Yomitan works
        against a stock AnkiConnect install with no setup). One deviation:
        Anki's own page origin also needs gates.anki_page_scripts.
        """
        allowlist = self.get("cors_allowlist", [])
        if origin in allowlist:
            return True
        if self.is_blocked_anki_page(origin):
            return False  # not even "*" or the 127.0.0.1 rule
        if "*" in allowlist:
            return True
        if "http://localhost" in allowlist:
            return (
                origin in ("http://127.0.0.1", "https://127.0.0.1")
                or origin.startswith(("http://127.0.0.1:", "https://127.0.0.1:"))
                or origin.startswith(EXTENSION_ORIGINS)
            )
        return False


# Module singleton. Seeded with safe defaults (auth off, empty allowlist,
# nothing persisted); start_server fills it with the real config before the
# server accepts requests.
settings = Settings(DEFAULTS)


def make_persist(mw: Any) -> PersistFn:
    """
    The one real persist callback: settings.update() may run on request
    threads, so hop to the main thread for addonManager writes.
    Fire-and-forget is fine - the in-memory settings are already updated.
    """
    def _persist(c: Dict[str, Any]) -> None:
        mw.taskman.run_on_main(lambda: mw.addonManager.writeConfig(ADDON_PACKAGE, dict(c)))
    return _persist


def apply_config(mw: Any, new_cfg: Dict[str, Any], *, write: bool) -> Dict[str, Any]:
    """
    Migrate `new_cfg`, persist it, and make it the live config. Shared by the
    config-editor callback (write=False - Anki already wrote the edited dict)
    and the settings dialog (write=True - nothing wrote yet). Main thread.
    """
    migrated, changed = _migrate(dict(new_cfg))
    if write or changed:
        mw.addonManager.writeConfig(ADDON_PACKAGE, migrated)
    settings.configure(migrated, persist=make_persist(mw))
    return migrated
