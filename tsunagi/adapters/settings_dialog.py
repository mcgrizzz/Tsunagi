"""
The settings form model and saving, used by the settings page
(settings_page.py): pure dict-in/dict-out logic for the plain fields, tested
headless, plus the save/AnkiConnect-handover path that runs on the main thread.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Tuple

from .config import ADDON_PACKAGE, DEFAULTS
from .settings import apply_config

MIB = 1024 * 1024


def generate_api_key() -> str:
    """A random URL-safe key: 32 characters, 192 bits."""
    return secrets.token_urlsafe(24)


class Field(NamedTuple):
    key: str
    section: str
    kind: str  # "bool" | "text" | "int" | "mib" | "choice" | "cors_list" (one per line)
    label: str
    # Only read at server startup; saving such a change makes the dialog
    # restart the embedded server so it still applies immediately.
    restart: bool = False
    tooltip: str = ""
    minimum: int = 0
    maximum: int = 0
    choices: Tuple[str, ...] = ()


# The form, in display order. Keys not listed here (gates aside, which render
# as their own section) never appear in the dialog and pass through saves
# untouched: import history, config_version, dev_watch_seconds.
FIELDS: Tuple[Field, ...] = (
    Field("enabled", "Connection", "bool", "Enable Tsunagi server", restart=True,
          tooltip="When off, the API server does not start with Anki."),
    # One Port field on the page sets both; a nonzero `port` wins (config.md).
    Field("port", "Connection", "int", "Port", restart=True, minimum=0, maximum=65535,
          tooltip="The port to listen on. Startup fails loudly if it is busy."),
    Field("prefer_port", "Connection", "int", "Port", restart=True,
          minimum=1, maximum=65535,
          tooltip="The port to listen on. Startup fails loudly if it is busy."),
    Field("host", "Access", "text", "Host", restart=True,
          tooltip="Bind address. 127.0.0.1 keeps the API local-only."),
    Field("allowed_hosts", "Access", "cors_list", "Other host names",
          tooltip="Names this computer is reached by through a proxy on it, such as "
                  "Tailscale Serve. One per line. Applies immediately."),
    Field("cors_allowlist", "Access", "cors_list", "Allowed website origins",
          tooltip="Browser origins allowed to call the API. \"*\" allows all; "
                  "\"http://localhost\" also covers 127.0.0.1 and browser "
                  "extensions. Applies immediately."),
    Field("log_level", "Advanced", "choice", "Log level", restart=True,
          choices=("critical", "error", "warning", "info", "debug")),
    Field("op_timeout_seconds", "Advanced", "int", "Operation timeout (seconds)",
          minimum=1, maximum=600,
          tooltip="How long a request may wait on Anki's collection. "
                  "Applies immediately."),
    Field("media_max_bytes", "Advanced", "mib", "Max upload size",
          minimum=1, maximum=4096,
          tooltip="Largest media file the API accepts. Applies immediately."),
    Field("media_fetch_timeout_seconds", "Advanced", "int", "Download timeout (seconds)",
          minimum=1, maximum=600,
          tooltip="Timeout when fetching media from a URL. Applies immediately."),
)

RESTART_KEYS = frozenset(f.key for f in FIELDS if f.restart)

# Labels/tooltips for known gates. Unknown keys (a newer config seen by older
# code) still render, using the raw key as label. Long-form docs live in
# config.md; a test keeps the two in lockstep.
GATE_INFO: Dict[str, Tuple[str, str]] = {
    "anki_page_scripts": (
        "Allow card templates and add-on pages",
        "Lets JavaScript in your cards and in other add-ons' pages inside Anki "
        "use the API. Leave off unless you use card templates or add-ons "
        "built for it: a shared deck could otherwise read and change your "
        "collection while you review.",
    ),
}
_UNKNOWN_GATE_TOOLTIP = "Opt-in switch - see the add-on documentation."


def _parse_cors(text: str) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        origin = line.strip()
        if origin and origin not in out:
            out.append(origin)
    return out


def form_values_from_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Widget-ready values for every field, plus a "gates" sub-dict."""
    values: Dict[str, Any] = {}
    for f in FIELDS:
        raw = cfg.get(f.key, DEFAULTS[f.key])
        if f.kind == "bool":
            values[f.key] = bool(raw)
        elif f.kind in ("int",):
            values[f.key] = int(raw)
        elif f.kind == "mib":
            values[f.key] = max(1, round(int(raw) / MIB))
        elif f.kind == "cors_list":
            values[f.key] = "\n".join(raw or [])
        else:  # "text" | "choice"
            values[f.key] = str(raw)
    values["gates"] = {k: bool(v) for k, v in
                       {**DEFAULTS["gates"], **(cfg.get("gates") or {})}.items()}
    return values


def config_from_form(cfg: Dict[str, Any], values: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    Apply form values on top of `cfg`. A key is overwritten only when its form
    value differs from what the form would show for `cfg` - untouched fields
    (including a media_max_bytes that isn't a whole MiB) survive byte-for-byte,
    and hidden keys pass through because they were never in the form.
    Returns (new_cfg, restart_needed).
    """
    baseline = form_values_from_config(cfg)
    new_cfg = dict(cfg)
    restart = False
    for f in FIELDS:
        if values[f.key] == baseline[f.key]:
            continue
        if f.kind == "mib":
            parsed: Any = int(values[f.key]) * MIB
        elif f.kind == "cors_list":
            parsed = _parse_cors(values[f.key])
            if parsed == list(cfg.get(f.key) or []):
                continue  # whitespace-only edit
        elif f.kind == "text":
            parsed = str(values[f.key]).strip()
            if parsed == baseline[f.key]:
                continue  # whitespace-only edit
        else:
            parsed = values[f.key]
        new_cfg[f.key] = parsed
        restart = restart or f.restart
    if values.get("gates", {}) != baseline["gates"]:
        # Always a fresh dict: the settings singleton's gates can alias
        # DEFAULTS["gates"] before the first configure().
        new_cfg["gates"] = {k: bool(v) for k, v in values["gates"].items()}
    return new_cfg, restart


def validate_values(values: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not str(values.get("host", "")).strip():
        errors.append("Host must not be empty.")
    for name in _parse_cors(str(values.get("allowed_hosts", ""))):
        if not re.fullmatch(r"[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\]", name):
            errors.append(f"Other host names: {name!r} is not a host name (no http:// or port).")
    for f in FIELDS:
        if f.kind in ("int", "mib") and f.maximum > 0:
            v = values.get(f.key)
            if not isinstance(v, int) or not (f.minimum <= v <= f.maximum):
                errors.append(f"{f.label} must be between {f.minimum} and {f.maximum}.")
    return errors


def gate_rows(cfg: Dict[str, Any]) -> List[Tuple[str, str, str, bool]]:
    """(key, label, tooltip, enabled) per gate - unknown gates included."""
    rows = []
    for key, value in sorted({**DEFAULTS["gates"], **(cfg.get("gates") or {})}.items()):
        label, tooltip = GATE_INFO.get(key, (key, _UNKNOWN_GATE_TOOLTIP))
        rows.append((key, label, tooltip, bool(value)))
    return rows


# ====================
# Saving (main thread; called by the settings page)
# ====================


def _restart_server(mw: Any, *, enabled: bool) -> None:
    """
    Apply server-level keys live: stop uvicorn and start it again on the
    just-saved config (start_server re-reads everything, including
    log_level). The stop doesn't block Anki, so requests in progress finish
    first (6.80). The one case that still needs an Anki restart is a server
    thread that won't die - its port may still be held.
    """
    from aqt.utils import showWarning, tooltip

    from ..app import server_url, start_server, stop_server_then

    def stopped(ok: bool) -> None:
        if not ok:
            showWarning("The previous Tsunagi server thread is still shutting "
                        "down, so its port may still be held. Restart Anki to "
                        "apply the server settings.")
            return
        start_server(mw)  # no-op (with a log line) when enabled is off
        url = server_url()
        if url:
            tooltip(f"Tsunagi server restarted on {url}")
        elif not enabled:
            tooltip("Tsunagi server stopped")
        else:
            # start_server caught the failure and will show its own delayed
            # tooltip with the reason; give immediate feedback too.
            showWarning("The Tsunagi server did not restart - see the console "
                        "for details.")

    stop_server_then(mw, stopped)


def _check_handover_port(cfg: Dict[str, Any]) -> None:
    from .config import _bindable

    if not cfg.get("enabled", True):
        return
    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port") or cfg.get("prefer_port") or 7777)
    if _bindable(host, port):
        return
    from ..app import server_url

    if server_url() == f"http://{host}:{port}":
        return  # Tsunagi itself already owns the selected address.
    raise ValueError(f"Port {port} is still in use. The AnkiConnect handover was cancelled.")


def save_settings(mw: Any, new_cfg: Dict[str, Any], *, disable_ankiconnect: bool = False) -> None:
    """Disable/stop AnkiConnect before committing settings for the port handover."""
    from .dialogs import (
        ANKICONNECT_ID,
        ankiconnect_import_record,
        ankiconnect_status,
        stop_ankiconnect_server,
    )

    if not disable_ankiconnect:
        apply_config(mw, new_cfg, write=True)
        return
    status = ankiconnect_status(mw.addonManager)
    if not status["installed"]:
        raise ValueError("AnkiConnect is no longer installed. Reopen settings and try again.")
    previous = dict(mw.addonManager.getConfig(ADDON_PACKAGE) or {})
    restore_server = None
    saving = False
    try:
        if status["enabled"]:
            mw.addonManager.toggleEnabled(ANKICONNECT_ID, enable=False)
        restore_server = stop_ankiconnect_server()
        _check_handover_port(new_cfg)
        new_cfg = {**new_cfg, **ankiconnect_import_record()}
        saving = True
        apply_config(mw, new_cfg, write=True)
    except Exception:
        try:
            if saving:
                apply_config(mw, previous, write=True)
        finally:
            try:
                if status["enabled"]:
                    mw.addonManager.toggleEnabled(ANKICONNECT_ID, enable=True)
            finally:
                if restore_server is not None:
                    restore_server()
        raise


def import_history_text(cfg: Dict[str, Any]) -> str:
    recorded = cfg.get("ankiconnect_imported_at")
    if recorded:
        try:
            local = datetime.fromisoformat(recorded).astimezone()
            return f"{local:%d %b %Y at %H:%M}"
        except (TypeError, ValueError, OverflowError):
            return "Unavailable"
    return "Not recorded"
