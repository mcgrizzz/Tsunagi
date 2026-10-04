# tsunagi/app.py
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, JSONResponse

from .adapters.anki import collection as anki_collection
from .adapters.config import choose_port, load_config
from .adapters.settings import make_persist, settings
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
    LOG_ENTRY,
    ApiKeyAuthMiddleware,
    DynamicCORSMiddleware,
    IdempotencyMiddleware,
    RequestLogMiddleware,
    check_route_permission,
    is_local_request,
    provided_key,
)
from .http.playground import API_DESCRIPTION
from .http.v1.addons import router as addons_router
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
from .log import log
from .shared.errors import register_exception_handlers
from .shared.permissions import PUBLIC, requires
from .shared.schemas.capabilities import CallerInfo, Versions, runtime_versions
from .shared.schemas.creation import IDEMPOTENCY_HELP
from .shared.schemas.wrappers import NULLABLE, ErrorBody
from .shared.version import ADDON_VERSION


def _log(msg: str) -> None: log.info(msg)

# FastAPI app with comprehensive documentation
app = FastAPI(
    title="Tsunagi",
    version=ADDON_VERSION,
    # The default /redoc points at redoc@next on jsdelivr, which now serves
    # the restructured redoc 3 alpha - browsers refuse it (MIME mismatch under
    # nosniff). A pinned /redoc route is defined below instead.
    redoc_url=None,
    dependencies=[Depends(check_route_permission)],
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
                   "description": "An app's key from Tsunagi settings. Needed from other devices, "
                                  "and wherever a keyless request has No access."},
        "BearerAuth": {"type": "http", "scheme": "bearer",
                       "description": "Alternative to the X-API-Key header."},
    })
    for path, operations in schema["paths"].items():
        if path not in AUTH_EXEMPT_PATHS:
            for method, operation in operations.items():
                if method in {"get", "post", "put", "patch", "delete", "head", "options"}:
                    operation["security"] = [{"ApiKey": []}, {"BearerAuth": []}]
    # Every write takes an Idempotency-Key (6.74); say so on each (6.103),
    # defined once and referred to. Reads sent as POST (`/query`) don't need one.
    key = {"$ref": "#/components/parameters/IdempotencyKey"}
    schema["components"].setdefault("parameters", {})["IdempotencyKey"] = {
        "name": "Idempotency-Key", "in": "header", "required": False,
        "description": IDEMPOTENCY_HELP, "schema": {"type": "string"}}
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method in {"post", "put", "patch", "delete"} and not path.endswith("/query"):
                parameters = [p for p in operation.get("parameters", []) if p.get("name") != "Idempotency-Key"]
                operation["parameters"] = [*parameters, key] if key not in parameters else parameters
    # 422 bodies: `detail` is a string like every error's, and FastAPI's list
    # of problems is in `errors` (register_exception_handlers).
    validation = schema.get("components", {}).get("schemas", {}).get("HTTPValidationError")
    if validation and "errors" not in validation["properties"]:  # FastAPI caches the schema
        validation["properties"] = {
            "detail": {"title": "Detail", "type": "string"},
            "errors": {**validation["properties"]["detail"], "title": "Errors"}}
        validation["required"] = ["detail", "errors"]
    from .http.v1.events import describe_events
    describe_events(schema)
    # Every error has the same shape (6.105): said once, as each operation's default answer.
    schema["components"]["schemas"].setdefault("ErrorBody", ErrorBody.schema())
    schema["components"].setdefault("responses", {})["Error"] = {
        "description": "An error: `detail` says what went wrong; on a 503, `reason` says why Anki can't answer now",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorBody"}}}}
    for operations in schema["paths"].values():
        for method, operation in operations.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                operation.setdefault("responses", {})["default"] = {"$ref": "#/components/responses/Error"}
    _show_field_names(schema.get("components", {}).get("schemas", {}))
    _drop_titles(schema)
    _share_repeats(schema)
    return schema


def _share_repeats(spec: dict) -> None:
    """A parameter or answer that several operations spell out the same way (a
    list's `limit`, a 422) is defined once in components and referred to."""
    import json

    def share(kind: str, entries: list, name_of) -> None:
        found: dict = {}
        for holder, key, value in entries:
            if "$ref" not in value:
                found.setdefault(json.dumps(value, sort_keys=True), []).append((holder, key, value))
        store = spec["components"].setdefault(kind, {})
        for same in found.values():
            if len(same) < 2:
                continue
            name = name_of(same[0][1], same[0][2])
            while name in store and store[name] != same[0][2]:
                name += "_"
            store[name] = same[0][2]
            for holder, key, _ in same:
                holder[key] = {"$ref": f"#/components/{kind}/{name}"}

    parameters, responses = [], []
    for operations in spec["paths"].values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            for i, parameter in enumerate(operation.get("parameters", [])):
                if "$ref" not in parameter and parameter.get("description") == parameter.get("schema", {}).get("description"):
                    parameter["schema"].pop("description", None)  # said once, on the parameter
                parameters.append((operation["parameters"], i, parameter))
            for status, response in operation.get("responses", {}).items():
                if not status.startswith("2"):   # an operation's own answers stay with it
                    responses.append((operation["responses"], status, response))
    share("parameters", parameters, lambda _, p: f"{p['in']}.{p['name']}")
    share("responses", responses, lambda status, _: {"422": "ValidationFailed"}.get(status, f"Status{status}"))


def _drop_titles(spec: dict) -> None:
    """Pydantic titles every schema and field ("Deck Name"); nothing reads them,
    and they were a tenth of the description. The field names and descriptions say it."""
    def strip(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                strip(item)
        elif isinstance(node, dict):
            if isinstance(node.get("title"), str):
                del node["title"]
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    for field in value.values():   # field names, not schema keywords
                        strip(field)
                elif key in ("items", "additionalProperties", "not", "anyOf", "allOf", "oneOf", "schema"):
                    strip(value)
    for component in spec.get("components", {}).get("schemas", {}).values():
        strip(component)
    for operations in spec["paths"].values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters", []):
                strip(parameter)
            for content in operation.get("requestBody", {}).get("content", {}).values():
                strip(content)
            for response in operation.get("responses", {}).values():
                for content in response.get("content", {}).values():
                    strip(content)


def _models(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _models(sub)


def _show_field_names(components):
    """
    Pydantic 1 writes schemas by alias (`cardIds`, `ivl`); answers and docs
    use the field names, so the description shows those (6.72). Aliases are
    still accepted on input.
    """
    for model in set(_models(BaseModel)):
        if not model.__module__.startswith(__package__ + "."):
            continue
        names = {f.alias: f.name for f in model.__fields__.values() if f.alias != f.name}
        if not names:
            continue
        own = model.schema()
        for component in components.values():
            if (component.get("title") == own.get("title")
                    and component.get("properties", {}).keys() == own.get("properties", {}).keys()):
                component["properties"] = {names.get(k, k): v
                                           for k, v in component["properties"].items()}
                if "required" in component:
                    component["required"] = [names.get(k, k) for k in component["required"]]


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
app.include_router(addons_router)
# AnkiBusyError / CollectionUnavailableError -> 503 with a reason
register_exception_handlers(app, syncing=lambda: anki_collection.syncing)

# Auth inner, CORS outside it (added last runs first) so auth 401s still carry
# CORS headers for allowed origins and disallowed origins never reach auth.
# The request log wraps both, so it sees what they refuse too. Idempotency
# keys innermost: a key belongs to the caller auth resolved.
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(ApiKeyAuthMiddleware, settings=settings)
app.add_middleware(DynamicCORSMiddleware, settings=settings)
app.add_middleware(RequestLogMiddleware, settings=settings)

# Replacement for the disabled default /redoc (see the FastAPI() call): same
# path (so AUTH_EXEMPT_PATHS still covers it), same page, working bundle.
@app.get("/redoc", include_in_schema=False, openapi_extra=requires(PUBLIC))
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
    operation_id="rootLandingPage",
    openapi_extra=requires(PUBLIC),
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
    operation_id="ankiConnectRpc",
    openapi_extra=requires(PUBLIC),  # each action declares its own
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
    local = is_local_request(request.scope)
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
    entry = request.scope.get(LOG_ENTRY)
    if entry is not None and error is None:
        entry["action"] = action
        entry["app"] = settings.resolve_caller(body.get("key"), local).name
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
        result = handle_ankiconnect_rpc(body, origin=origin, local=local)
        if entry is not None and isinstance(result, dict) and isinstance(result.get("error"), str):
            entry["error"] = result["error"][:200]  # AnkiConnect errors come back as 200
        return JSONResponse(result)

    return await run_in_threadpool(dispatch_response)

# Actions listing endpoint
@app.get(
    "/actions",
    response_model=dict,
    summary="List available AnkiConnect actions",
    description="Get a list of all registered AnkiConnect-compatible actions",
    tags=["AnkiConnect Compatibility"],
    operation_id="listAnkiConnectActions",
    openapi_extra=requires(PUBLIC),
)
def list_ankiconnect_actions() -> dict:
    """
    List all registered AnkiConnect actions.

    Returns:
        Dictionary with 'actions' key containing list of action names
    """
    return get_available_actions()

class CollectionHealth(BaseModel):
    profile: Optional[str] = Field(description="Open profile name; null when none is open", **NULLABLE)
    state: Literal["ready", "syncing", "closed", "busy"] = Field(description=(
        "ready; syncing; closed (no collection, e.g. during a full sync); "
        "busy (Anki did not answer a trivial read within a second). "
        "A 503 body carries the same value as reason"))


class Health(BaseModel):
    ok: bool = Field(description="Whether the server is running")
    server: str = Field(description="Server name")
    version: str = Field(description="Legacy release version; use versions for explicit identifiers")
    versions: Versions
    port: int = Field(description="Port number the server is listening on")
    collection: CollectionHealth
    caller: CallerInfo = Field(description=(
        "Who this request counts as, and what became of its key (X-API-Key or a Bearer "
        "token). Needs no profile open"))

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
    description=("Verify the Tsunagi server is running and responsive. Public; `caller` says who "
                 "the request counts as, so sending your key checks it."),
    tags=["Health"],
    operation_id="checkHealth",
    openapi_extra=requires(PUBLIC),
)
def health(request: Request) -> Health:
    """Get API health status including version, port and collection state."""
    from aqt import mw
    sent = provided_key(request.scope)
    who = settings.resolve_caller(sent, is_local_request(request.scope))
    caller = CallerInfo.of(who, sent, request.headers.get("host", ""))
    return Health(
        ok=True,
        server="tsunagi",
        version=ADDON_VERSION,
        versions=runtime_versions(),
        port=_SERVER_STATE.port or 0,
        collection=CollectionHealth(profile=mw.pm.name,
                                    state=anki_collection.collection_state()),
        caller=caller,
    )

def _serve(server: Any, session_id: str) -> None:
    try:
        server.run()
    except Exception:
        log.exception("The server crashed")
    finally:
        from .adapters.events import broker
        broker.begin_drain(session_id)

def start_server(mw) -> None:
    if _SERVER_STATE.started: return
    from .adapters import ops
    ops.closing.clear()   # requests wait on Anki again (stop_server set it)
    session_id = None
    try:
        cfg = load_config()
        if not cfg.get("enabled", True):
            _log("disabled via config; not starting"); return

        settings.configure(cfg, persist=make_persist(mw))
        settings.anki_page_origin = f"http://127.0.0.1:{mw.mediaServer.getPort()}"

        # Other add-ons' action providers (backlog 2b-P); all are loaded by now.
        from .adapters import addon_actions
        addon_actions.collect()

        host = cfg["host"]
        port = choose_port(cfg)

        from .adapters.events import broker
        if mw.col is None:
            raise RuntimeError("No collection is open")
        session_id = broker.start_session(mw.col)
        from aqt.qt import QTimer

        from .adapters.change_scan import ChangeScan
        scan_timer = QTimer(mw)
        scan_timer.setSingleShot(True)
        broker.scanner = ChangeScan(mw.col, lambda s: scan_timer.start(int(s * 1000)))
        scan_timer.timeout.connect(broker.scanner.flush)

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
            # uvicorn's 5 s default closes idle connections just as clients
            # polling every few seconds reuse them (backlog 6.48). config.md
            # tells clients the value.
            timeout_keep_alive=75,
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
        _set_app_nap(allowed=False)
    except Exception as e:
        if session_id is not None:
            broker.begin_drain(session_id)
        log.exception("Server failed to start")
        msg = f"Tsunagi failed to start: {e}"
        try:
            from aqt.qt import QTimer
            from aqt.utils import tooltip
            # Delay past Anki's own startup tooltips (sync etc.) so the
            # warning is actually visible, and keep it up longer.
            QTimer.singleShot(3000, lambda: tooltip(msg, period=8000))
        except Exception:
            pass  # headless / no Qt available

def _set_app_nap(*, allowed: bool) -> None:
    """
    macOS App Nap throttles an app in the background, which stalls API
    requests while Anki is not in front. Anki leaves App Nap on and lets
    add-ons turn it off themselves (ankitects/anki#4460, closed so add-ons
    like this one do it); Tsunagi does while its server runs. No-op off macOS
    or without the helper; never fatal.
    """
    try:
        from aqt._macos_helper import macos_helper
        if macos_helper is not None:
            (macos_helper.enable_appnap if allowed else macos_helper.disable_appnap)()
    except Exception:
        log.warning("Could not %s App Nap", "restore" if allowed else "turn off", exc_info=True)


def server_url() -> Optional[str]:
    """Base URL if the server is up, else None."""
    st = _SERVER_STATE
    return f"http://{st.host}:{st.port}" if st.started else None


def begin_stop(reason: str = "shutdown") -> Callable[[], bool]:
    """
    Signal uvicorn to exit without waiting for it. `reason` is what open event
    streams are told in their close event. Returns whether the server thread
    has ended (so the port is free); the dev reload polls it from a timer, so
    requests waiting on Anki's main thread can finish meanwhile.
    """
    st = _SERVER_STATE
    thread = st.thread
    if st.started:
        try:
            # Close open event streams BEFORE signaling uvicorn: its graceful
            # shutdown waits on in-flight responses, and an SSE stream is
            # in-flight for its whole life. Generators poll this flag and exit
            # within ~0.5s.
            from .adapters.events import broker
            broker.begin_drain(reason=reason)
        except Exception:
            log.exception("Closing the event streams failed")
        finally:
            if st.server is not None:
                st.server.should_exit = True
            st.thread = None
            st.server = None
            st.port = None
            st.started = False
            _set_app_nap(allowed=True)
    return lambda: thread is None or not thread.is_alive()


def stop_server_then(mw: Any, then: Callable[[bool], None], reason: str = "shutdown") -> None:
    """
    Stop without blocking Anki's main thread, so requests waiting on it finish
    (6.80); then(stopped) runs on the main thread once the server thread has
    ended (the port is free), or then(False) if it hasn't within 30 s.
    """
    from ._kiso.ui import wait_until

    wait_until(mw, begin_stop(reason), lambda: then(True), timeout=30.0, on_timeout=lambda: then(False))


def stop_server(reason: str = "shutdown") -> bool:
    """
    Signal uvicorn to exit and wait briefly, blocking Anki's main thread; for
    closing the profile, which must finish before the collection closes.
    `reason` is what open event streams are told in their close event. Requests
    waiting on the main thread can't finish meanwhile, so they end at once with
    a 503 (ops.closing). Anywhere else, use stop_server_then().

    Returns False if the thread outlived the wait, which means the port may
    still be held.
    """
    from .adapters import ops

    thread = _SERVER_STATE.thread
    if thread is not None:
        ops.closing.set()
    stopped = begin_stop(reason)
    if thread is not None:
        thread.join(5)
    if not stopped():
        log.warning("Server thread did not stop within 5s; abandoning it (daemon)")
        return False
    return True
