# tsunagi/app.py
import sys
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from .adapters.config import ADDON_PACKAGE, choose_port, load_config
from .adapters.settings import settings
from .http.compat import (
    models as _compat_models,  # noqa: F401  (side-effect import: registers action handlers)
)
from .http.compat.ankiconnect import (
    AnkiConnectRequest,
    AnkiConnectResponse,
    get_available_actions,
    handle_ankiconnect_rpc,
)
from .http.middleware import ApiKeyAuthMiddleware, DynamicCORSMiddleware
from .http.v1.models import router as models_router
from .shared.errors import register_exception_handlers


def _log(msg: str) -> None: print("[tsunagi]", msg, file=sys.stdout)

# FastAPI app with comprehensive documentation
app = FastAPI(
    title="Tsunagi",
    version="0.0.1",
    description="REST API for Anki. Query and modify models (note types), fields, and templates.",
    license_info={"name": "MIT"},
    openapi_tags=[
        {
            "name": "Models",
            "description": "Note types (models) and their fields and templates. Models define the structure of cards in Anki."
        },
        {
            "name": "Health",
            "description": "API health and status checks"
        },
        {
            "name": "AnkiConnect Compatibility",
            "description": "AnkiConnect-compatible RPC endpoint for gradual migration"
        }
    ]
)

app.include_router(models_router)
register_exception_handlers(app)  # AnkiBusyError / CollectionUnavailableError -> 503

# Auth inner, CORS outermost (added last runs first) so auth 401s still carry
# CORS headers for allowed origins and disallowed origins never reach auth.
app.add_middleware(ApiKeyAuthMiddleware, settings=settings)
app.add_middleware(DynamicCORSMiddleware, settings=settings)

# Root GET endpoint - Tsunagi landing page
@app.get(
    "/",
    summary="Tsunagi API landing page",
    description="Welcome page with links to API documentation",
    tags=["Health"],
    operation_id="rootLandingPage"
)
def root_landing_page():
    """
    Root landing page for Tsunagi API.

    Redirects to OpenAPI documentation or provides info about available endpoints.
    """
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")

# Root POST endpoint - AnkiConnect compatibility
@app.post(
    "/",
    response_model=AnkiConnectResponse,
    summary="AnkiConnect RPC endpoint",
    description="AnkiConnect-compatible POST endpoint at root. Send action and params in JSON body.",
    tags=["AnkiConnect Compatibility"],
    operation_id="ankiConnectRpc"
)
def ankiconnect_rpc_endpoint(body: AnkiConnectRequest, request: Request) -> AnkiConnectResponse:
    """
    Handle AnkiConnect-style RPC requests at the root path.

    This endpoint mimics AnkiConnect's API for backward compatibility.
    AnkiConnect clients can point to http://localhost:7777/ instead of http://localhost:8765/

    Example request:
        POST http://localhost:7777/
        {
            "action": "findModelsById",
            "params": {"modelIds": [123, 456]},
            "version": 6
        }
    """
    return handle_ankiconnect_rpc(body, origin=request.headers.get("origin"))

# Actions listing endpoint
@app.get(
    "/actions",
    response_model=dict,
    summary="List available AnkiConnect actions",
    description="Get a list of all registered AnkiConnect-compatible actions",
    tags=["AnkiConnect Compatibility"],
    operation_id="listAnkiConnectActions"
)
def list_ankiconnect_actions() -> dict:
    """
    List all registered AnkiConnect actions.

    Returns:
        Dictionary with 'actions' key containing list of action names
    """
    return get_available_actions()

class Health(BaseModel):
    ok: bool = Field(description="Whether the server is running")
    server: str = Field(description="Server name")
    version: str = Field(description="API version")
    port: int = Field(description="Port number the server is listening on")

@dataclass
class _ServerState:
    thread: Optional[threading.Thread] = None
    server: Optional[Any] = None  # uvicorn.Server (kept so stop_server can signal it)
    port: Optional[int] = None
    started: bool = False
    host: str = "127.0.0.1"

_SERVER_STATE = _ServerState()

@app.get(
    "/v1/health",
    response_model=Health,
    summary="Check API health",
    description="Verify the Tsunagi server is running and responsive",
    tags=["Health"],
    operation_id="checkHealth"
)
def health() -> Health:
    """Get API health status including version and port."""
    return Health(
        ok=True,
        server="tsunagi",
        version=app.version or "0.0.1",
        port=_SERVER_STATE.port or 0
    )

def _serve(server: Any) -> None:
    try:
        server.run()
    except Exception:
        _log(f"[fatal] uvicorn crashed:\n{traceback.format_exc()}")

def start_server(mw) -> None:
    if _SERVER_STATE.started: return
    try:
        cfg = load_config()
        if not cfg.get("enabled", True):
            _log("disabled via config; not starting"); return

        from .adapters import ops
        ops.OP_TIMEOUT = float(cfg.get("op_timeout_seconds", 15))

        def _persist(c: dict) -> None:
            # settings.update() may run on request threads; hop to the main
            # thread for addonManager writes. Fire-and-forget is fine - the
            # in-memory settings are already updated.
            mw.taskman.run_on_main(lambda: mw.addonManager.writeConfig(ADDON_PACKAGE, dict(c)))

        settings.configure(cfg, persist=_persist)

        host = cfg["host"]
        port = choose_port(cfg)

        import uvicorn
        server = uvicorn.Server(uvicorn.Config(
            app, host=host, port=port, loop="asyncio",
            http="h11", access_log=False,
            log_level=cfg.get("log_level", "warning"),
        ))
        t = threading.Thread(target=_serve, args=(server,),
                             daemon=True, name="tsunagi-http")
        t.start()
        _SERVER_STATE.thread = t
        _SERVER_STATE.server = server
        _SERVER_STATE.port = port
        _SERVER_STATE.host = host
        _SERVER_STATE.started = True
        _log(f"listening on http://{host}:{port}")
    except Exception as e:
        _log(f"[fatal] start_server failed:\n{traceback.format_exc()}")
        msg = f"Tsunagi failed to start: {e}"
        try:
            from aqt.qt import QTimer
            from aqt.utils import tooltip
            # Delay past Anki's own startup tooltips (sync etc.) so the
            # warning is actually visible, and keep it up longer.
            QTimer.singleShot(3000, lambda: tooltip(msg, period=8000))
        except Exception:
            pass  # headless / no Qt available

def stop_server() -> None:
    """Signal uvicorn to exit and wait briefly; called on profile close."""
    st = _SERVER_STATE
    if not st.started:
        return
    try:
        if st.server is not None:
            st.server.should_exit = True
        if st.thread is not None:
            st.thread.join(5)
            if st.thread.is_alive():
                _log("server thread did not stop within 5s; abandoning (daemon)")
    except Exception:
        _log(f"stop_server failed:\n{traceback.format_exc()}")
    finally:
        st.thread = None
        st.server = None
        st.port = None
        st.started = False
