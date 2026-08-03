import socket
from typing import Tuple

# Top-level package name of the addon (= installed folder name); used as the
# key for addonManager.getConfig/writeConfig.
ADDON_PACKAGE = __name__.split(".")[0]

DEFAULTS = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 0,
    "prefer_port": 7777,
    "api_key": "",
    # AnkiConnect's default. The "http://localhost" entry also covers
    # 127.0.0.1 origins and browser extensions (see Settings.is_origin_allowed).
    "cors_allowlist": ["http://localhost"],
    "log_level": "warning",
    "op_timeout_seconds": 15,
    "media_max_bytes": 67108864,          # 64 MiB
    "media_fetch_timeout_seconds": 30,
    "media_allow_local_path": False,      # server-side file reads: off by default
    "ankiconnect_import_offered": False,
    "config_version": 3,
}

def _migrate(cfg: dict) -> Tuple[dict, bool]:
    """Fill defaults and upgrade legacy keys. Returns (cfg, changed). Pure."""
    changed = False
    # v1 auto-minted a "token" nobody ever saw or validated; copying it into
    # api_key would silently turn auth ON and break existing clients. Drop it.
    if "token" in cfg:
        cfg.pop("token")
        changed = True
    for k, v in DEFAULTS.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
    # v3 introduced the AnkiConnect-compatible default allowlist. Installs
    # created before it have an empty list, which blocks browser extensions
    # (Yomitan) - add the entry once so they behave like a fresh install.
    if cfg.get("config_version", 1) < 3:
        allowlist = cfg.get("cors_allowlist") or []
        if "http://localhost" not in allowlist:
            cfg["cors_allowlist"] = ["http://localhost", *allowlist]
        cfg["config_version"] = 3
        changed = True
    return cfg, changed

def load_config() -> dict:
    from aqt import mw
    cfg = mw.addonManager.getConfig(ADDON_PACKAGE) or {}
    cfg, changed = _migrate(cfg)
    if changed:
        mw.addonManager.writeConfig(ADDON_PACKAGE, cfg)
    return cfg

def _bindable(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
