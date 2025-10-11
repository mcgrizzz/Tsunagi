# tsunagi/app.py
import threading, traceback, sys
from dataclasses import dataclass
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel

from .http.v1.models import router as models_router
from .adapters.config import load_config, choose_port

def _log(msg: str) -> None: print("[tsunagi]", msg, file=sys.stdout)

app = FastAPI(title="Tsunagi", version="0.0.1")
app.include_router(models_router)

class Health(BaseModel):
    ok: bool; server: str; version: str; port: int

@dataclass
class _ServerState:
    thread: Optional[threading.Thread] = None
    port: Optional[int] = None
    started: bool = False
    host: str = "127.0.0.1"

_SERVER_STATE = _ServerState()

@app.get("/v1/health", response_model=Health)
def health() -> Health:
    return Health(ok=True, server="tsunagi",
                  version=app.version or "0.0.1",
                  port=_SERVER_STATE.port or 0)

def _serve(host: str, port: int, log_level: str) -> None:
    try:
        import uvicorn
        uvicorn.Server(uvicorn.Config(
            app, host=host, port=port, loop="asyncio",
            http="h11", access_log=False, log_level=log_level
        )).run()
    except Exception:
        _log(f"[fatal] uvicorn crashed:\n{traceback.format_exc()}")

def start_server(mw) -> None:
    if _SERVER_STATE.started: return
    try:
        cfg = load_config()
        if not cfg.get("enabled", True):
            _log("[tsunagi] disabled via config; not starting"); return
        host = cfg["host"]
        port = choose_port(cfg)
        _SERVER_STATE.port = port
        _SERVER_STATE.host = host
        t = threading.Thread(target=_serve,
                             args=(host, port, cfg.get("log_level","warning")),
                             daemon=True, name="tsunagi-http")
        t.start()
        _SERVER_STATE.thread = t 
        _SERVER_STATE.started = True
        print(f"[tsunagi] listening on http://{host}:{port}")
    except Exception:
        _log(f"[fatal] start_server failed:\n{traceback.format_exc()}")
