import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tsunagi.adapters.settings import Settings
from tsunagi.http.middleware import ApiKeyAuthMiddleware


def make_client(settings: Settings) -> TestClient:
    app = FastAPI()

    @app.get("/")
    def root():
        return {"ok": True}

    @app.post("/")
    def rpc():
        return {"ok": True}

    @app.get("/v1/health")
    def health():
        return {"ok": True}

    @app.get("/v1/thing")
    def thing():
        return {"ok": True}

    @app.get("/v1/events")
    def events():
        return {"ok": True}

    app.add_middleware(ApiKeyAuthMiddleware, settings=settings)
    return TestClient(app)


@pytest.fixture()
def keyed_client():
    return make_client(Settings({"api_key": "sekrit"}))


class TestAuthOff:
    def test_empty_key_everything_passes(self):
        client = make_client(Settings({"api_key": ""}))
        for path in ("/", "/v1/health", "/v1/thing"):
            assert client.get(path).status_code == 200


class TestAuthOn:
    def test_missing_header_is_401(self, keyed_client):
        assert keyed_client.get("/v1/thing").status_code == 401

    def test_wrong_key_is_401(self, keyed_client):
        assert keyed_client.get("/v1/thing", headers={"X-Api-Key": "nope"}).status_code == 401

    def test_x_api_key_passes(self, keyed_client):
        assert keyed_client.get("/v1/thing", headers={"X-Api-Key": "sekrit"}).status_code == 200

    def test_bearer_passes(self, keyed_client):
        resp = keyed_client.get("/v1/thing", headers={"Authorization": "Bearer sekrit"})
        assert resp.status_code == 200

    def test_basic_auth_is_401(self, keyed_client):
        resp = keyed_client.get("/v1/thing", headers={"Authorization": "Basic c2Vrcml0"})
        assert resp.status_code == 401

    def test_options_exempt(self, keyed_client):
        assert keyed_client.options("/v1/thing").status_code != 401

    def test_health_exempt(self, keyed_client):
        # Liveness probe stays reachable so clients can test the connection
        assert keyed_client.get("/v1/health").status_code == 200

    def test_compat_root_post_exempt(self, keyed_client):
        # POST / delegates key checking to the dispatcher's body "key" field
        assert keyed_client.post("/").status_code == 200

    def test_root_and_docs_exempt(self, keyed_client):
        assert keyed_client.get("/").status_code == 200
        assert keyed_client.get("/openapi.json").status_code == 200
        assert keyed_client.get("/docs").status_code == 200


class TestEventsQueryParamKey:
    # Browser EventSource can't send headers, so /v1/events - and only
    # /v1/events - also accepts the key as ?api_key=.

    def test_query_key_passes_on_events(self, keyed_client):
        assert keyed_client.get("/v1/events?api_key=sekrit").status_code == 200

    def test_wrong_query_key_is_401(self, keyed_client):
        assert keyed_client.get("/v1/events?api_key=nope").status_code == 401

    def test_query_key_rejected_elsewhere(self, keyed_client):
        assert keyed_client.get("/v1/thing?api_key=sekrit").status_code == 401

    def test_header_still_works_on_events(self, keyed_client):
        resp = keyed_client.get("/v1/events", headers={"X-Api-Key": "sekrit"})
        assert resp.status_code == 200

    def test_header_wins_over_query_param(self, keyed_client):
        # A provided header is authoritative; the query param is a fallback.
        resp = keyed_client.get("/v1/events?api_key=sekrit",
                                headers={"X-Api-Key": "nope"})
        assert resp.status_code == 401
