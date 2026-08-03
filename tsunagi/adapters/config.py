import secrets
import socket

from aqt import mw

DEFAULTS = {
    "enabled": True, 
    "host": "127.0.0.1",
    "port": 0, 
    "prefer_port": 7777,
    "token": "", 
    "cors_allowlist": [],
    "log_level": "warning",
    "op_timeout_seconds": 15,
    "config_version": 1,
}

def load_config() -> dict:
    cfg = mw.addonManager.getConfig(__name__.split(".")[0]) or {}
    # migrate or fill defaults
    for k, v in DEFAULTS.items():
        cfg.setdefault(k, v)
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(24)
        mw.addonManager.writeConfig(__name__.split(".")[0], cfg)
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
