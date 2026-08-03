"""
Pure-ASGI auth and CORS middleware.

Both read from an injected Settings object on every request so config changes
(API key edits, origins granted at runtime via requestPermission) apply live.
Pure ASGI instead of BaseHTTPMiddleware: neither needs the request body or a
buffered response, and starlette 0.36's BaseHTTPMiddleware adds task-group
overhead and streaming quirks.
"""
from __future__ import annotations

import secrets

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, PlainTextResponse

# Paths reachable without an API key:
# - "/"     : GET redirects to docs; POST is the AnkiConnect RPC, which checks
#             the AnkiConnect-style top-level "key" body field in the
#             dispatcher instead of headers.
# - docs    : opened in a browser, where custom headers can't be sent. The
#             schema leaks structure, not data, on a loopback-bound server.
AUTH_EXEMPT_PATHS = {"/", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


class ApiKeyAuthMiddleware:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        api_key: str = self.settings.get("api_key", "")
        if not api_key:  # empty key = auth off (AnkiConnect semantics)
            return await self.app(scope, receive, send)
        if scope["method"] == "OPTIONS" or scope["path"] in AUTH_EXEMPT_PATHS:
            return await self.app(scope, receive, send)

        headers = Headers(scope=scope)
        provided = headers.get("x-api-key")
        if provided is None:
            auth = headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()
        if provided is not None and secrets.compare_digest(provided.encode(), api_key.encode()):
            return await self.app(scope, receive, send)

        resp = JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
        await resp(scope, receive, send)


class DynamicCORSMiddleware:
    """
    CORS against the live cors_allowlist ("*" allowed). Unknown origins get a
    hard 403 - that's the actual enforcement when no API key is set (blocks
    cross-origin side effects, not just response reads). Exception: the
    AnkiConnect root path "/" stays reachable from any origin so that
    requestPermission can be called and its response read; origin enforcement
    for "/" happens in the compat dispatcher (as AnkiConnect does it).
    """

    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is None:  # not a cross-origin browser request
            return await self.app(scope, receive, send)

        allowed = self.settings.is_origin_allowed(origin)
        is_compat_root = scope["path"] == "/"

        # Preflight
        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            if allowed or is_compat_root:
                resp = PlainTextResponse("OK", headers={
                    # Echo the concrete origin, never the literal "*"
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": headers.get("access-control-request-headers", "*"),
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                })
            else:
                resp = PlainTextResponse("Disallowed CORS origin", status_code=403,
                                         headers={"Vary": "Origin"})
            return await resp(scope, receive, send)

        # Actual request
        if allowed or (is_compat_root and scope["method"] == "POST"):
            async def send_with_cors(message):
                if message["type"] == "http.response.start":
                    hdrs = MutableHeaders(scope=message)
                    hdrs["Access-Control-Allow-Origin"] = origin
                    hdrs.append("Vary", "Origin")
                await send(message)
            return await self.app(scope, receive, send_with_cors)

        resp = PlainTextResponse("Disallowed CORS origin", status_code=403,
                                 headers={"Vary": "Origin"})
        await resp(scope, receive, send)
