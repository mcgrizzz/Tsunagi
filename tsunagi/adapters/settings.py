"""
Live, thread-safe view of the addon config.

Middleware and the compat dispatcher read from the module singleton on every
request, so runtime changes (e.g. an origin granted via requestPermission)
take effect immediately. Persistence is an injected callback so this module
stays importable without aqt (tests construct their own Settings).
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from .config import DEFAULTS

PersistFn = Callable[[Dict[str, Any]], None]

# Browser-extension origin schemes covered by the "http://localhost" entry
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://", "safari-web-extension://")


class Settings:
    def __init__(self, config: Dict[str, Any], persist: Optional[PersistFn] = None):
        self._lock = threading.Lock()
        self._config = dict(config)
        self._persist = persist

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
        against a stock AnkiConnect install with no setup).
        """
        allowlist = self.get("cors_allowlist", [])
        if "*" in allowlist or origin in allowlist:
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
