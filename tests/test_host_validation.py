"""The Host boundary applies before CORS and compatibility permission routing."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tsunagi.adapters.settings import Settings
from tsunagi.http.middleware import DynamicCORSMiddleware


@pytest.fixture()
def host_app():
    settings = Settings({"host": "127.0.0.1", "cors_allowlist": ["*"]})
    app = FastAPI()
    calls = []

    @app.api_route("/v1/probe", methods=["GET", "POST"])
    @app.post("/")
    def probe():
        calls.append(True)
        return {"ok": True}

    app.add_middleware(DynamicCORSMiddleware, settings=settings)
    with TestClient(app, base_url="http://127.0.0.1:7777") as client:
        yield client, settings, calls


@pytest.mark.parametrize("method,path", [("GET", "/v1/probe"), ("POST", "/v1/probe"),
                                         ("POST", "/"), ("OPTIONS", "/")])
@pytest.mark.parametrize("origin", [None, "http://evil.example:7777", "https://allowed.test"])
def test_untrusted_host_never_reaches_app(host_app, method, path, origin):
    client, _, calls = host_app
    headers = {"Host": "evil.example:7777", "X-Forwarded-Host": "localhost:7777"}
    if origin:
        headers["Origin"] = origin
    if method == "OPTIONS":
        headers["Access-Control-Request-Method"] = "POST"
    response = client.request(method, path, headers=headers)
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers
    assert not calls


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST:7777", "127.0.0.1:7777",
                                  "127.0.0.2", "[::1]:7777", "[0:0:0:0:0:0:0:1]"])
def test_loopback_hosts_work_without_origin(host_app, host):
    client, _, calls = host_app
    assert client.get("/v1/probe", headers={"Host": host}).status_code == 200
    assert calls == [True]


@pytest.mark.parametrize("host", ["", "localhost:", "localhost:invalid", "localhost:65536",
                                  "user@localhost", "localhost/path", "localhost?query",
                                  "localhost#fragment", "[::1", "localhost.evil.example"])
def test_invalid_or_disguised_authorities_are_rejected(host_app, host):
    client, _, calls = host_app
    assert client.get("/v1/probe", headers={"Host": host}).status_code == 403
    assert not calls


@pytest.mark.parametrize("configured,host", [("192.0.2.10", "192.0.2.10:7777"),
                                             ("anki.example", "ANKI.EXAMPLE:7777"),
                                             ("2001:db8::1", "[2001:db8:0:0:0:0:0:1]:7777")])
def test_configured_host_is_exact_and_reads_live_settings(host_app, configured, host):
    client, settings, calls = host_app
    assert client.get("/v1/probe", headers={"Host": host}).status_code == 403
    settings.update(host=configured)
    assert client.get("/v1/probe", headers={"Host": host}).status_code == 200
    assert calls == [True]
    for wildcard in ("0.0.0.0", "::", "*"):
        settings.update(host=wildcard)
        assert client.get("/v1/probe", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("hosts", [[], [b"localhost", b"evil.example"],
                                   [b"localhost", b"localhost"], [b"localhost\t"],
                                   [b"localhost\x00"], [b"localhost\n"]])
def test_missing_duplicate_or_control_character_host_is_rejected(hosts):
    async def run():
        async def downstream(*args):
            pytest.fail("Invalid Host must not reach the application")

        messages = []

        async def send(message):
            messages.append(message)

        scope = {"type": "http", "method": "GET", "path": "/v1/probe",
                 "headers": [(b"host", host) for host in hosts]}
        middleware = DynamicCORSMiddleware(downstream, Settings({}))
        await middleware(scope, None, send)
        assert messages[0]["status"] == 403

    asyncio.run(run())
