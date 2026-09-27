"""
Live, thread-safe view of the addon config.

Middleware and the compat dispatcher read from the module singleton on every
request, so runtime changes (e.g. an origin granted via requestPermission)
take effect immediately. Persistence is an injected callback so this module
stays importable without aqt (tests construct their own Settings).
"""
from __future__ import annotations

import secrets
import threading
from ipaddress import ip_address
from typing import Any, Callable, Dict, Optional, Tuple

from ..shared.permissions import BUILTIN_ROLES, GRANTS, NO_ACCESS, Caller
from .config import ADDON_PACKAGE, DEFAULTS, _migrate

PersistFn = Callable[[Dict[str, Any]], None]

NO_KEY_LOCAL = "No key, this computer"
NO_KEY_REMOTE = "No key, other devices"

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
        gates = self.get("gates") or {}
        # Anki keeps a saved "gates" dict whole, so gates added later fall back
        # to their defaults.
        return bool(gates.get(name, DEFAULTS["gates"].get(name, False)))

    def role(self, role_id: Any) -> Tuple[str, frozenset]:
        """(name, grants) of a role; an unknown role grants nothing."""
        spec = {**BUILTIN_ROLES, **(self.get("roles") or {})}.get(role_id)
        if not isinstance(spec, dict):
            return BUILTIN_ROLES[NO_ACCESS]["name"], frozenset()
        grants = spec.get("grants")
        grants = frozenset(g for g in grants if g in GRANTS) if isinstance(grants, list) else frozenset()
        return str(spec.get("name") or role_id), grants

    def resolve_caller(self, key: Any, local: bool) -> Caller:
        """
        The app a key belongs to, else the "No key" row for where the request
        came from (`local`: this computer, see middleware.is_local_request).
        A key that matches no app counts as no key, as in AnkiConnect: it
        gains nothing a keyless request would not get.
        """
        match = None
        if isinstance(key, str) and key:
            for app in self.get("apps") or []:
                app_key = app.get("key") if isinstance(app, dict) else None
                # Compare against every app so timing does not reveal which matched.
                if (isinstance(app_key, str) and app_key
                        and secrets.compare_digest(key.encode(), app_key.encode())):
                    match = match or app
        if match is not None:
            name, role_id = str(match.get("name") or "App"), match.get("role")
        else:
            key = None
            name = NO_KEY_LOCAL if local else NO_KEY_REMOTE
            row = "no_key_local_role" if local else "no_key_remote_role"
            role_id = self.get(row, DEFAULTS[row])
        role_name, grants = self.role(role_id)
        return Caller(name=name, role=str(role_id), role_name=role_name,
                      grants=grants, key=key, local=local)

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
