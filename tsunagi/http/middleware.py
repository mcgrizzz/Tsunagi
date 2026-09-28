"""
Pure-ASGI auth and CORS middleware.

Both read from an injected Settings object on every request so config changes
(API key edits, origins granted at runtime via requestPermission) apply live.
Pure ASGI instead of BaseHTTPMiddleware: neither needs the request body or a
buffered response, and starlette's BaseHTTPMiddleware adds task-group
overhead and streaming quirks.
"""
from __future__ import annotations

from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, PlainTextResponse

from ..adapters.settings import is_loopback_host
from ..shared.permissions import ADDON, PUBLIC, allows, current_caller, denied_message

# Paths the auth middleware lets through without resolving a caller:
# - "/"        : GET redirects to docs; POST is the AnkiConnect RPC, which
#                checks the AnkiConnect-style top-level "key" body field in
#                the dispatcher instead of headers.
# - docs       : opened in a browser, where custom headers can't be sent. The
#                schema leaks structure, not data, on a loopback-bound server.
# - /v1/health : liveness probe; leaks nothing an open port doesn't already.
AUTH_EXEMPT_PATHS = {"/", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect", "/v1/health"}


# Set by a proxy in front of Tsunagi. Tailscale Serve always adds
# Tailscale-User-Login and strips it from what clients send; the others are the
# usual reverse-proxy headers. A local program sending one only loses access.
PROXY_HEADERS = ("tailscale-user-login", "forwarded", "x-forwarded-for",
                 "x-forwarded-host", "x-real-ip")


def is_local_request(scope) -> bool:
    """
    From this computer: the peer is loopback, the Host names loopback, and no
    proxy says it forwarded the request. Behind a local proxy such as
    Tailscale Serve the peer is always 127.0.0.1, so the other two decide.
    """
    headers = Headers(scope=scope)
    if any(name in headers for name in PROXY_HEADERS):
        return False
    client = scope.get("client")
    try:
        if not client or not ip_address(client[0]).is_loopback:
            return False
    except ValueError:
        return False
    try:
        hostname = urlsplit("//" + (headers.get("host") or "")).hostname
    except ValueError:
        return False
    return hostname is not None and is_loopback_host(hostname)


class ApiKeyAuthMiddleware:
    """
    Resolves who is calling (an app by its key, else a "No key" row) and makes
    it the request's current_caller. A keyless request whose row is No access
    gets 401; what each route needs is checked by check_route_permission.
    """

    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["method"] == "OPTIONS" or scope["path"] in AUTH_EXEMPT_PATHS:
            return await self.app(scope, receive, send)

        headers = Headers(scope=scope)
        provided = headers.get("x-api-key")
        if provided is None:
            auth = headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()
        if provided is None and scope["path"] == "/v1/events":
            # The event stream is consumed by browser EventSource, which -
            # like the docs pages above - cannot send custom headers. For
            # this one path the key is also accepted as a query parameter.
            from urllib.parse import parse_qs
            values = parse_qs(scope.get("query_string", b"").decode()).get("api_key")
            if values:
                provided = values[0]
        caller = self.settings.resolve_caller(provided, is_local_request(scope))
        if caller.key is None and not caller.grants:
            resp = JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
            return await resp(scope, receive, send)
        token = current_caller.set(caller)
        try:
            await self.app(scope, receive, send)
        finally:
            current_caller.reset(token)


async def check_route_permission(request: Request) -> None:
    """App-wide dependency: the caller must have the route's x-permission."""
    extra = getattr(request.scope.get("route"), "openapi_extra", None) or {}
    permission = extra.get("x-permission")
    if permission == PUBLIC:
        return
    caller = current_caller.get()
    if caller is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    if permission is None:  # tests/test_permissions.py keeps this unreachable
        raise HTTPException(status_code=403, detail="This route declares no permission")
    if permission == ADDON:
        return  # the handler checks addon:<provider>/<item>
    if not allows(caller.grants, permission):
        raise HTTPException(status_code=403, detail=denied_message(caller, permission))


def _host_allowed(headers: Headers, bind_host: str, allowed_hosts: Any = ()) -> bool:
    hosts = headers.getlist("host")
    if len(hosts) != 1:
        return False
    authority = hosts[0]
    if not authority or any(ord(char) <= 32 or ord(char) >= 127 for char in authority):
        return False
    try:
        parsed = urlsplit("//" + authority)
        # Reject userinfo, paths and malformed ports instead of extracting a
        # trusted name from an invalid HTTP authority.
        if (parsed.netloc != authority or parsed.username is not None
                or parsed.hostname is None or authority.endswith(":")):
            return False
        _ = parsed.port
        hostname = parsed.hostname
    except ValueError:
        return False
    if hostname == "localhost":
        return True
    # Names this computer is reached by through a proxy (allowed_hosts), e.g.
    # the tailnet name in front of Tailscale Serve.
    if isinstance(allowed_hosts, list) and hostname.lower() in (
            str(h).strip().lower() for h in allowed_hosts):
        return True
    try:
        address = ip_address(hostname)
        if address.is_loopback:
            return True
        # Rebinding needs a domain name, so a plain IP is safe to accept once
        # other devices may connect (they need an API key). A phone then
        # reaches a 0.0.0.0 bind at this computer's LAN address.
        if not is_loopback_host(bind_host):
            return True
        hostname = str(address)
    except ValueError:
        pass
    configured = str(bind_host).strip("[]").lower()
    try:
        configured = str(ip_address(configured))
    except ValueError:
        pass
    # Wildcard bind addresses are compared literally, never as allow-all rules.
    return hostname == configured


class DynamicCORSMiddleware:
    """
    CORS against the live cors_allowlist ("*" allowed). Unknown origins get a
    hard 403 - that's the actual enforcement for keyless local requests (blocks
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
        # Host is a trust boundary even without Origin (same-origin GETs),
        # and before the compatibility permission handshake or CORS allowlist.
        if not _host_allowed(headers, self.settings.get("host", "127.0.0.1"),
                             self.settings.get("allowed_hosts") or []):
            return await PlainTextResponse("Disallowed Host header", status_code=403)(
                scope, receive, send,
            )
        origin = headers.get("origin")
        if origin is None:  # not a cross-origin browser request
            return await self.app(scope, receive, send)

        # Browser POSTs from our own API reference carry Origin too. They are
        # same-origin requests; the external-site allowlist does not apply.
        host = headers.get("host")
        same_origin = bool(host) and origin == f"{scope.get('scheme', 'http')}://{host}"
        allowed = same_origin or self.settings.is_origin_allowed(origin)
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
