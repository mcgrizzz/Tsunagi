# __init__.py at the add-on ROOT (sibling of meta.json)

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# The vendored web stack (`kiso vendor`), first on sys.path before anything imports it.
from .tsunagi._kiso import vendor  # noqa: E402  (stdlib only)

SHARED = vendor.add_to_path(BASE)
# The server can't run on another version of these; other bundled libraries
# loaded from elsewhere are only logged.
CRITICAL = ("fastapi", "starlette", "pydantic", "uvicorn")

from .tsunagi.log import log  # noqa: E402  (stdlib only; after the path setup)


def _log_vendor_conflicts() -> None:
    """Say which module and whose file, so it is the first line of a bug
    report instead of a mystery."""
    try:
        clashes = vendor.find_clashes(SHARED, CRITICAL)
        if clashes:
            log.warning("Vendored modules already imported from elsewhere, their "
                        "versions win: %s", "; ".join(f"{c.name} ({c.file})" for c in clashes))
    except Exception:
        pass

# Catches copies loaded by addons that imported before us; runs again at
# profile open, when every addon has been imported, to catch the rest.
_log_vendor_conflicts()

# The wiring with Anki (settings action, Tools menu, log file, add-on switch,
# dev reload) is Kiso's Addon; the running part is tsunagi/feature.py. The
# callbacks here import Tsunagi's modules inside the function, so a reload
# brings in the new code.

try:
    # gui_hooks too: the tests' stand-in aqt has an mw but no hooks.
    from aqt import gui_hooks, mw  # noqa: F401
except ImportError:
    # Not running inside Anki (tests / tooling importing the addon root) - no-op.
    mw = None

addon = None

if mw is not None:
    from .tsunagi._kiso.addon import Addon

    def _vendor_refusal():
        """A message if another add-on loaded a different version of the web
        stack; the server would fail with a traceback on it (backlog 8.3a)."""
        try:
            _log_vendor_conflicts()   # all add-ons are imported by now
            blocking = [c for c in vendor.find_clashes(SHARED, CRITICAL) if c.blocks]
            return vendor.refusal("Tsunagi", blocking, vendor.addon_name(mw.addonManager)) if blocking else None
        except Exception:
            log.exception("Vendor check failed")
            return None

    def _start():
        from .tsunagi.feature import Feature
        return Feature(mw, __name__, _vendor_refusal)

    def _settings():
        from .tsunagi.adapters.settings_page import open_settings
        open_settings(mw)

    def _config(_addon):
        # At profile open, after a reload, and when the user saves Anki's raw
        # JSON config editor (the fallback for direct meta.json edits; the
        # settings page applies its own saves). Per-request keys (apps, roles,
        # gates, cors_allowlist, media_*, op_timeout_seconds) apply at once;
        # host, port, log_level and enabled wait for a restart. write=False:
        # Anki already wrote it.
        from .tsunagi.adapters.settings import apply_config
        apply_config(mw, mw.addonManager.getConfig(__name__) or {}, write=False)

    # Turning Tsunagi off in Tools -> Add-ons takes effect only at restart;
    # offer to stop the server now (and restart it if turned back on).
    _switch = None

    def _toggled(_addon, enabled):
        global _switch
        from .tsunagi.adapters.addon_toggle import ServerSwitch, ask_to_stop
        if _switch is None:
            _switch = ServerSwitch(running=_server_running,
                                   ask_to_stop=lambda: ask_to_stop(mw.app.activeWindow() or mw),
                                   stop=_stop_now, start=_start_again)
        _switch(enabled)

    def _server_running() -> bool:
        from .tsunagi.app import server_url
        return server_url() is not None

    def _stop_now() -> None:
        from aqt.utils import tooltip

        from .tsunagi.app import stop_server
        stop_server("shutdown")
        tooltip("Tsunagi's server stopped.")

    def _start_again() -> None:
        from aqt.utils import tooltip

        from .tsunagi.app import server_url, start_server
        start_server(mw)
        if server_url():   # a failed start shows its own message
            tooltip("Tsunagi's server is running again.")

    # Registered at import time, so the settings work even when the server is
    # disabled or failed to start; the server itself starts at profile open.
    addon = Addon(__name__, inner="tsunagi", start=_start, stop=lambda feature: feature.teardown(),
                  settings=_settings, menu="Tsunagi Settings...", on_config=_config,
                  on_toggle=_toggled, log_also=("uvicorn",))
    addon.install()


def reload_addon() -> str:
    """
    Dev helper: run the code now on disk without restarting Anki. From Anki's
    debug console (Ctrl+Shift+;):

        import tsunagi; tsunagi.reload_addon()

    `kiso sync --watch` copies the source into the installed add-on and Anki
    reloads it by itself. A reload waits for the server's requests in progress
    to finish, without blocking Anki; the result then shows in a tooltip.

    Only this add-on's own package is purged. The vendored libraries in
    lib/shared stay loaded on purpose: re-importing pydantic mid-session would
    give every schema a new base class and break `isinstance` against models
    Anki already holds. Editing lib/ or this file still needs a restart.
    """
    if addon is None:
        return "not running inside Anki"
    from aqt.utils import tooltip
    return addon.reload(then=lambda message: tooltip(f"Tsunagi: {message}", period=3000))
