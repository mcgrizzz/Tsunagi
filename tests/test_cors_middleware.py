import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tsunagi.adapters.settings import Settings
from tsunagi.http.middleware import ApiKeyAuthMiddleware, DynamicCORSMiddleware

ORIGIN = "https://allowed.test"
OTHER = "https://unknown.test"


def make_app(settings: Settings) -> TestClient:
    app = FastAPI()

    @app.post("/")
    def rpc():
        return {"ok": True}

    @app.get("/v1/thing")
    def thing():
        return {"ok": True}

    app.add_middleware(DynamicCORSMiddleware, settings=settings)
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture()
def settings():
    return Settings({"cors_allowlist": [ORIGIN]})


@pytest.fixture()
def client(settings):
    return make_app(settings)


class TestSimpleRequests:
    def test_no_origin_untouched(self, client):
        resp = client.get("/v1/thing")
        assert resp.status_code == 200
        assert "access-control-allow-origin" not in resp.headers

    def test_allowed_origin_echoed_with_vary(self, client):
        resp = client.get("/v1/thing", headers={"Origin": ORIGIN})
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == ORIGIN
        assert "Origin" in resp.headers.get("vary", "")

    def test_unknown_origin_is_403_without_cors_headers(self, client):
        resp = client.get("/v1/thing", headers={"Origin": OTHER})
        assert resp.status_code == 403
        assert "access-control-allow-origin" not in resp.headers

    def test_unknown_origin_compat_root_post_passes(self, client):
        # requestPermission must be reachable (and readable) from any origin
        resp = client.post("/", headers={"Origin": OTHER})
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == OTHER

    def test_wildcard_echoes_concrete_origin(self):
        client = make_app(Settings({"cors_allowlist": ["*"]}))
        resp = client.get("/v1/thing", headers={"Origin": OTHER})
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == OTHER  # not "*"


class TestPreflight:
    def test_allowed_preflight(self, client):
        resp = client.options("/v1/thing", headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-api-key, content-type",
        })
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == ORIGIN
        assert "GET" in resp.headers["access-control-allow-methods"]
        assert resp.headers["access-control-allow-headers"] == "x-api-key, content-type"
        assert resp.headers["access-control-max-age"] == "600"

    def test_unknown_origin_preflight_is_403(self, client):
        resp = client.options("/v1/thing", headers={
            "Origin": OTHER, "Access-Control-Request-Method": "GET",
        })
        assert resp.status_code == 403
        assert "access-control-allow-origin" not in resp.headers

    def test_unknown_origin_preflight_on_compat_root_passes(self, client):
        resp = client.options("/", headers={
            "Origin": OTHER, "Access-Control-Request-Method": "POST",
        })
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == OTHER


class TestLiveAllowlist:
    def test_grant_takes_effect_without_restart(self, settings, client):
        assert client.get("/v1/thing", headers={"Origin": OTHER}).status_code == 403
        settings.add_cors_origin(OTHER)  # what requestPermission does on accept
        resp = client.get("/v1/thing", headers={"Origin": OTHER})
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == OTHER


@pytest.mark.parametrize("base_url", ["http://localhost:7777", "http://127.0.0.1:8765", "http://[::1]:7777"])
def test_docs_same_origin_post_still_requires_api_key(base_url):
    config = Settings({"cors_allowlist": [], "api_key": "test-key"})
    app = FastAPI()
    calls = []

    @app.post("/v1/probe")
    def probe():
        calls.append(True)
        return {"ok": True}

    app.add_middleware(ApiKeyAuthMiddleware, settings=config)
    app.add_middleware(DynamicCORSMiddleware, settings=config)
    # The bundled TestClient predates IPv6 URL parsing; set the wire Host
    # explicitly so IPv6 still exercises the middleware's origin comparison.
    with TestClient(app, headers={"Host": base_url.removeprefix("http://")}) as client:
        assert client.post("/v1/probe", headers={"Origin": base_url}).status_code == 401
        assert not calls
        response = client.post("/v1/probe", headers={"Origin": base_url, "X-API-Key": "test-key"})
        assert response.status_code == 200
        assert len(calls) == 1
        for origin in ("https://unknown.test", base_url + ".evil.test", "null"):
            assert client.post("/v1/probe", headers={"Origin": origin, "X-API-Key": "test-key"}).status_code == 403
        assert len(calls) == 1


@pytest.mark.parametrize("origin", ["https://localhost:7777", "http://localhost:7778", "http://127.0.0.1:7777"])
def test_same_origin_requires_matching_scheme_host_and_port(origin):
    with make_app(Settings({"cors_allowlist": []})) as client:
        response = client.get("http://localhost:7777/v1/thing", headers={"Origin": origin})
        assert response.status_code == 403
