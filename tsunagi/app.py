# tsunagi/app.py
import json
import sys
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, JSONResponse

from .adapters.config import ADDON_PACKAGE, choose_port, load_config
from .adapters.settings import apply_config, make_persist, settings
from .http.compat import (
    actions as _compat_actions,  # noqa: F401  (side-effect import: registers action handlers)
)
from .http.compat.ankiconnect import (
    get_available_actions,
    handle_ankiconnect_rpc,
    origin_allowed_for,
)
from .http.middleware import (
    AUTH_EXEMPT_PATHS,
    ApiKeyAuthMiddleware,
    DynamicCORSMiddleware,
)
from .http.playground import API_DESCRIPTION
from .http.v1.cards import router as cards_router
from .http.v1.collection import router as collection_router
from .http.v1.deck_configs import router as deck_configs_router
from .http.v1.decks import router as decks_router
from .http.v1.events import router as events_router
from .http.v1.fsrs import router as fsrs_router
from .http.v1.gui import router as gui_router
from .http.v1.media import router as media_router
from .http.v1.models import router as models_router
from .http.v1.notes import router as notes_router
from .http.v1.reviews import router as reviews_router
from .http.v1.tags import router as tags_router
from .shared.errors import register_exception_handlers
from .shared.schemas.capabilities import Versions, runtime_versions
from .shared.version import ADDON_VERSION


def _log(msg: str) -> None: print("[tsunagi]", msg, file=sys.stdout)

# FastAPI app with comprehensive documentation
app = FastAPI(
    title="Tsunagi",
    version=ADDON_VERSION,
    # The default /redoc points at redoc@next on jsdelivr, which now serves
    # the restructured redoc 3 alpha - browsers refuse it (MIME mismatch under
    # nosniff). A pinned /redoc route is defined below instead.
    redoc_url=None,
    description=API_DESCRIPTION,
    license_info={"name": "MIT"},
    openapi_tags=[
        {
            "name": "Models",
            "description": "Note types (models) and their fields and templates. Models define the structure of cards in Anki."
        },
        {
            "name": "Decks",
            "description": "Deck hierarchy (nested names use '::'). Filtered (dynamic) decks appear in reads; mutations operate on normal decks."
        },
        {
            "name": "Notes",
            "description": "Notes hold the content; cards are generated from them. Supports Anki search syntax via the `search` parameter."
        },
        {
            "name": "Cards",
            "description": "Cards generated from notes by a model's templates. Reads support Anki search syntax; scheduling changes are batch verb routes (POST /v1/cards:suspend and friends)."
        },
        {
            "name": "Tags",
            "description": "Tags across the collection. Nesting uses '::', and operations apply to a tag and its children together, like Anki's own."
        },
        {
            "name": "Deck Configs",
            "description": "Deck options groups (scheduling limits and intervals). Returned as Anki's config dicts verbatim so newer keys survive a round trip."
        },
        {
            "name": "Media",
            "description": "Files in the collection's media folder. Downloads stream raw bytes; uploads report the name Anki actually stored."
        },
        {
            "name": "FSRS",
            "description": "FSRS parameter optimization, evaluation and simulation. Optimize/evaluate run as async jobs (submit, then poll /v1/jobs/{id}); the simulator answers synchronously."
        },
        {
            "name": "Events",
            "description": "Live collection events as Server-Sent Events: operations, reviews, sync, and full-refresh signals."
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

# Middleware authentication is not visible to FastAPI's schema generator.
_generate_openapi = app.openapi


def openapi_with_auth():
    schema = _generate_openapi()
    schema.setdefault("components", {}).setdefault("securitySchemes", {}).update({
        "ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key",
                   "description": "Required when an API key is configured in Tsunagi settings."},
        "BearerAuth": {"type": "http", "scheme": "bearer",
                       "description": "Alternative to the X-API-Key header."},
    })
    for path, operations in schema["paths"].items():
        if path not in AUTH_EXEMPT_PATHS:
            for method, operation in operations.items():
                if method in {"get", "post", "put", "patch", "delete", "head", "options"}:
                    operation["security"] = [{"ApiKey": []}, {"BearerAuth": []}]
    return schema


app.openapi = openapi_with_auth

app.include_router(models_router)
app.include_router(decks_router)
app.include_router(notes_router)
app.include_router(cards_router)
app.include_router(tags_router)
app.include_router(deck_configs_router)
app.include_router(reviews_router)
app.include_router(fsrs_router)
app.include_router(collection_router)
app.include_router(gui_router)
app.include_router(media_router)
app.include_router(events_router)
register_exception_handlers(app)  # AnkiBusyError / CollectionUnavailableError -> 503

# Auth inner, CORS outermost (added last runs first) so auth 401s still carry
# CORS headers for allowed origins and disallowed origins never reach auth.
app.add_middleware(ApiKeyAuthMiddleware, settings=settings)
app.add_middleware(DynamicCORSMiddleware, settings=settings)

# Replacement for the disabled default /redoc (see the FastAPI() call): same
# path (so AUTH_EXEMPT_PATHS still covers it), same page, working bundle.
@app.get("/redoc", include_in_schema=False)
def redoc_page():
    from fastapi.openapi.docs import get_redoc_html
    return get_redoc_html(
        openapi_url="/openapi.json",
        title=f"{app.title} - ReDoc",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js",
    )


# Root GET endpoint - Tsunagi landing page
@app.get(
    "/",
    summary="Tsunagi API landing page",
    description="Scalar API reference and interactive request console",
    response_class=HTMLResponse,
    tags=["Health"],
    operation_id="rootLandingPage"
)
def root_landing_page():
    """Serve Scalar against the same OpenAPI document used by Swagger and ReDoc."""
    from .http.playground import PLAYGROUND_HTML
    return HTMLResponse(PLAYGROUND_HTML, headers={"Cache-Control": "no-store"})

# Root POST endpoint - AnkiConnect compatibility
@app.post(
    "/",
    response_model=None,  # replies are bare values (version<=4) or envelopes - shape varies
    summary="AnkiConnect RPC endpoint",
    description="AnkiConnect-compatible POST endpoint at root. Send action and params in JSON body.",
    tags=["AnkiConnect Compatibility"],
    operation_id="ankiConnectRpc"
)
async def ankiconnect_rpc_endpoint(request: Request) -> Any:
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
    # The body is parsed by hand rather than declared as a typed parameter:
    # AnkiConnect clients check only `error` and then read `result`, so a
    # FastAPI 422 body ({"detail": ...}) sails past their guard and crashes
    # them on the next property access. Errors must use the RPC envelope;
    # successful version <= 4 replies remain bare values.
    from .http.compat.request_validation import request_error

    raw_body = await request.body()
    origin = request.headers.get("origin")
    try:
        # Upstream decodes UTF-8 explicitly; json.loads(bytes) would also
        # accept UTF-16/32 and silently consume a UTF-8 BOM.
        body = json.loads(raw_body.decode("utf-8"))
    except ValueError as exc:
        body = None
        error = str(exc)
    else:
        error = request_error(body)

    # Only a schema-valid permission request bypasses the origin gate.
    action = body["action"] if error is None else ""
    if not origin_allowed_for(action, origin):
        # Same wire response AnkiConnect gives a disallowed origin
        from fastapi import Response
        return Response(status_code=403)

    if error is not None:
        if not raw_body:
            return {"apiVersion": "AnkiConnect v.6"}
        return {"result": None, "error": error}

    # Anki work happens off the event loop: the handlers block on QueryOp /
    # CollectionOp round-trips to Anki's threads.
    def dispatch_response() -> JSONResponse:
        # Compatibility handlers already return JSON values. Encode once here
        # instead of having FastAPI recursively convert the full result again.
        # Keep large-response encoding off the event loop with the Anki work.
        return JSONResponse(handle_ankiconnect_rpc(body, origin=origin))

    return await run_in_threadpool(dispatch_response)

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
    version: str = Field(description="Legacy release version; use versions for explicit identifiers")
    versions: Versions
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
        version=ADDON_VERSION,
        versions=runtime_versions(),
        port=_SERVER_STATE.port or 0
    )

def _serve(server: Any, session_id: str) -> None:
    try:
        server.run()
    except Exception:
        _log(f"[fatal] uvicorn crashed:\n{traceback.format_exc()}")
    finally:
        from .adapters.events import broker
        broker.begin_drain(session_id)

def start_server(mw) -> None:
    if _SERVER_STATE.started: return
    session_id = None
    try:
        cfg = load_config()
        if not cfg.get("enabled", True):
            _log("disabled via config; not starting"); return

        from .adapters import ops
        ops.OP_TIMEOUT = float(cfg.get("op_timeout_seconds", 15))

        settings.configure(cfg, persist=make_persist(mw))

        def _on_config_updated(new_cfg: dict) -> None:
            # Anki calls this (main thread) when the user saves the raw JSON
            # config editor - kept as the fallback path for direct meta.json
            # edits; the settings dialog calls apply_config itself (and also
            # restarts the server for server-level keys, which this path does
            # not - here host/port/op_timeout_seconds/log_level/enabled still
            # need an Anki restart). Per-request keys (gates, api_key,
            # cors_allowlist, media_*) apply immediately either way.
            # write=False: Anki already wrote the edited dict.
            apply_config(mw, new_cfg, write=False)

        mw.addonManager.setConfigUpdatedAction(ADDON_PACKAGE, _on_config_updated)

        host = cfg["host"]
        port = choose_port(cfg)

        from .adapters.events import broker
        if mw.col is None:
            raise RuntimeError("No collection is open")
        session_id = broker.start_session(mw.col)

        import uvicorn
        server = uvicorn.Server(uvicorn.Config(
            app, host=host, port=port, loop="asyncio",
            http="h11", access_log=False,
            log_level=cfg.get("log_level", "warning"),
            # None = never call logging.config.dictConfig: uvicorn's default
            # config probes sys.stdout.isatty(), which crashes under Anki's
            # debug console (its Stream has no isatty), and rewriting the host
            # app's logging config isn't ours to do. log_level/access_log
            # still apply; records fall to Python's last-resort stderr handler.
            log_config=None,
            # Backstop for shutdown: in-flight responses (an open event
            # stream) would otherwise be waited on forever. The drain flag
            # in stop_server closes streams first; this catches stragglers.
            timeout_graceful_shutdown=3,
        ))
        t = threading.Thread(target=_serve, args=(server, session_id),
                             daemon=True, name="tsunagi-http")
        t.start()
        _SERVER_STATE.thread = t
        _SERVER_STATE.server = server
        _SERVER_STATE.port = port
        _SERVER_STATE.host = host
        _SERVER_STATE.started = True
        _log(f"listening on http://{host}:{port}")
    except Exception as e:
        if session_id is not None:
            broker.begin_drain(session_id)
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

def server_url() -> Optional[str]:
    """Base URL if the server is up, else None."""
    st = _SERVER_STATE
    return f"http://{st.host}:{st.port}" if st.started else None


def stop_server() -> bool:
    """
    Signal uvicorn to exit and wait briefly; called on profile close.

    Returns False if the thread outlived the wait, which means the port may
    still be held - the dev reload needs to know that before rebinding.
    """
    st = _SERVER_STATE
    stopped = True
    if not st.started:
        return True
    try:
        # Close open event streams BEFORE signaling uvicorn: its graceful
        # shutdown waits on in-flight responses, and an SSE stream is
        # in-flight for its whole life. Generators poll this flag and exit
        # within ~0.5s, well inside the join below.
        from .adapters.events import broker
        broker.begin_drain()
        if st.server is not None:
            st.server.should_exit = True
        if st.thread is not None:
            st.thread.join(5)
            if st.thread.is_alive():
                _log("server thread did not stop within 5s; abandoning (daemon)")
                stopped = False
    except Exception:
        _log(f"stop_server failed:\n{traceback.format_exc()}")
        stopped = False
    finally:
        st.thread = None
        st.server = None
        st.port = None
        st.started = False
    return stopped
