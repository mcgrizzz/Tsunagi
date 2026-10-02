import socket
import sys
from typing import Tuple

from .._kiso import config as kiso_config

# Top-level package name of the addon (= installed folder name); used as the
# key for addonManager.getConfig/writeConfig.
ADDON_PACKAGE = __name__.split(".")[0]

DEFAULTS = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 0,
    "prefer_port": 7777,
    # Who may do what (backlog 6.5a). Apps are {"name", "key", "role"};
    # requests without a key use one of the two no_key roles. `roles` holds
    # user-made roles and edited built-ins (shared/permissions.py).
    "apps": [],
    "no_key_local_role": "default",
    "no_key_remote_role": "none",
    "roles": {},
    # Add-on items the user approved, with the impact approved:
    # {"fsrs_helper/easy_days": "undoable"} (backlog 2b-P).
    "addon_enabled": {},
    # AnkiConnect's default. The "http://localhost" entry also covers
    # 127.0.0.1 origins and browser extensions (see Settings.is_origin_allowed).
    "cors_allowlist": ["http://localhost"],
    # Host names this computer is reached by through a proxy on it, such as
    # Tailscale Serve ("pc.tailnet.ts.net"); the Host check accepts them.
    "allowed_hosts": [],
    "log_level": "warning",
    "op_timeout_seconds": 15,
    "media_max_bytes": 67108864,          # 64 MiB
    "media_fetch_timeout_seconds": 30,
    # Switches about the server rather than a caller; what callers may do is
    # set by roles. Read live, so toggling takes effect without a restart.
    "gates": {
        "anki_page_scripts": False,           # card templates and add-on pages
    },
    "ankiconnect_import_offered": False,
    "ankiconnect_imported_at": None,
    "ankiconnect_ignore_origins": [],
    "config_version": 5,
}
CONFIG_VERSION = DEFAULTS["config_version"]
# Dicts of the user's own entries, filled as a whole or not at all.
FREE_FORM = ("roles", "addon_enabled")

# The app an AnkiConnect settings import fills with AnkiConnect's key.
DEFAULT_APP = "AnkiConnect key"


def default_app_key(cfg: dict) -> str:
    for app in cfg.get("apps") or []:
        if isinstance(app, dict) and app.get("name") == DEFAULT_APP:
            return str(app.get("key") or "")
    return ""


def with_default_app_key(cfg: dict, key: str) -> list:
    """cfg's apps with DEFAULT_APP's key set (it keeps its role and on/off), or removed if empty."""
    apps, kept = [], {"role": "default"}
    for app in cfg.get("apps") or []:
        if isinstance(app, dict) and app.get("name") == DEFAULT_APP:
            kept = {k: app[k] for k in ("role", "enabled") if k in app} or kept
        else:
            apps.append(app)
    return [{"name": DEFAULT_APP, "key": key, "role": "default", **kept}, *apps] if key else apps


def _v3(cfg: dict) -> None:
    # v3 introduced the AnkiConnect-compatible default allowlist. Installs
    # created before it have an empty list, which blocks browser extensions
    # (Yomitan) - add the entry once so they behave like a fresh install.
    allowlist = cfg.get("cors_allowlist") or []
    if "http://localhost" not in allowlist:
        cfg["cors_allowlist"] = ["http://localhost", *allowlist]


def _v4(cfg: dict) -> None:
    # v4 grouped the opt-in switches under "gates". The old flat
    # media_allow_local_path is now the local_files permission; drop it.
    gates = dict(DEFAULTS["gates"])
    gates.update(cfg.get("gates") or {})
    cfg.pop("media_allow_local_path", None)
    cfg["gates"] = gates


def _v5(cfg: dict) -> None:
    # v5: Kiso's dev watch (a DEV_WATCH file from `kiso sync`) replaced dev_watch_seconds.
    cfg.pop("dev_watch_seconds", None)


def _migrate(cfg: dict) -> Tuple[dict, bool]:
    """Fill defaults and upgrade legacy keys. Returns (cfg, changed). Pure.
    A config without config_version is a new one (Anki's config.json has it)."""
    # v1 auto-minted a "token" nobody ever saw or validated; copying it into
    # api_key would silently turn auth ON and break existing clients. Drop it.
    had_token = "token" in cfg
    migrated, changed = kiso_config.migrate({k: v for k, v in cfg.items() if k != "token"}, DEFAULTS,
                                            CONFIG_VERSION, [(3, _v3), (4, _v4), (5, _v5)], FREE_FORM)
    return migrated, changed or had_token


def load_config() -> dict:
    from aqt import mw
    return kiso_config.load(mw.addonManager, ADDON_PACKAGE, _migrate)

def _bindable(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # As uvicorn binds (asyncio sets SO_REUSEADDR on POSIX only): without it,
    # connections a stopped server closed (TIME_WAIT) make the port look busy
    # on Linux and macOS. On Windows it would allow binding over a live server.
    if sys.platform != "win32":
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()

def choose_port(cfg: dict) -> int:
    host = cfg["host"]
    explicit = int(cfg.get("port") or 0)
    prefer = int(cfg.get("prefer_port") or 8765)
    if explicit > 0:
        if _bindable(host, explicit): return explicit
        raise RuntimeError(f"Configured port {explicit} is busy")
    if _bindable(host, prefer): return prefer
    # No silent ephemeral fallback: clients are configured for the preferred
    # port, so a random one just hides the conflict.
    raise RuntimeError(f"Port {prefer} is busy (another server or addon using it?)")
