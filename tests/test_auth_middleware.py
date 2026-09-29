import pytest
from access import key_required
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tsunagi.adapters.settings import Settings
from tsunagi.http.middleware import ApiKeyAuthMiddleware, is_local_request

LOCAL = ("127.0.0.1", 50000)
LAN = ("192.168.1.20", 50000)


def make_client(settings: Settings, peer=LOCAL, host="127.0.0.1") -> TestClient:
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
    return TestClient(app, base_url=f"http://{host}", client=peer)


@pytest.fixture()
def keyed_client():
    return make_client(Settings(key_required("sekrit")))


class TestNoKeyRows:
    def test_this_computer_uses_default_out_of_the_box(self):
        client = make_client(Settings({}))
        for path in ("/", "/v1/health", "/v1/thing"):
            assert client.get(path).status_code == 200

    def test_other_devices_get_no_access_out_of_the_box(self):
        client = make_client(Settings({}), peer=LAN)
        assert client.get("/v1/thing").status_code == 401
        assert client.get("/v1/health").status_code == 200

    def test_other_devices_row_can_be_opened(self):
        client = make_client(Settings({"no_key_remote_role": "read_only"}), peer=LAN)
        assert client.get("/v1/thing").status_code == 200

    def test_this_computer_row_can_be_closed(self):
        client = make_client(Settings({"no_key_local_role": "none"}))
        assert client.get("/v1/thing").status_code == 401

    def test_a_proxied_request_with_an_outside_host_is_not_local(self):
        # Tailscale Serve: the peer is loopback, the Host is the tailnet name.
        client = make_client(Settings({}), host="anki.tailnet.ts.net")
        assert client.get("/v1/thing").status_code == 401

    def test_unknown_key_counts_as_no_key(self):
        # As in AnkiConnect: a stale key in a client still works while no key
        # is required, and gains nothing beyond the No key row.
        client = make_client(Settings({}))
        assert client.get("/v1/thing", headers={"X-Api-Key": "stale"}).status_code == 200

    def test_a_key_works_from_other_devices(self):
        client = make_client(Settings(key_required("sekrit")), peer=LAN,
                             host="192.168.1.10:7777")
        assert client.get("/v1/thing", headers={"X-Api-Key": "sekrit"}).status_code == 200


@pytest.mark.parametrize("peer, host, local", [
    ("127.0.0.1", "127.0.0.1:7777", True),
    ("127.0.0.1", "localhost:7777", True),
    ("::1", "[::1]:7777", True),
    ("127.0.0.1", "anki.tailnet.ts.net", False),
    ("192.168.1.20", "127.0.0.1:7777", False),
    ("testclient", "127.0.0.1", False),
])
def test_is_local_request(peer, host, local):
    scope = {"client": (peer, 1), "headers": [(b"host", host.encode())]}
    assert is_local_request(scope) is local


@pytest.mark.parametrize("header", [b"tailscale-user-login", b"x-forwarded-for", b"forwarded",
                                    b"x-forwarded-host", b"x-real-ip"])
def test_a_proxied_request_is_never_this_computer(header):
    # Tailscale Serve connects from 127.0.0.1 and may send a loopback Host;
    # its Tailscale-User-Login (or any proxy header) marks it as from elsewhere.
    scope = {"client": ("127.0.0.1", 1),
             "headers": [(b"host", b"127.0.0.1:7777"), (header, b"alice@example.com")]}
    assert is_local_request(scope) is False


def test_through_tailscale_serve_a_keyless_phone_gets_no_access(client, reset_settings):
    from access import key_required
    reset_settings.update(allowed_hosts=["pc.tailnet.ts.net"])
    serve = {"Host": "pc.tailnet.ts.net", "Tailscale-User-Login": "alice@example.com"}
    assert client.get("/v1/capabilities", headers=serve).status_code == 401
    reset_settings.update(**{**key_required("phone-key", name="Phone"), "no_key_local_role": "default"})
    caller = client.get("/v1/capabilities", headers={**serve, "X-Api-Key": "phone-key"}).json()["caller"]
    assert caller == {"name": "Phone", "role": "Default", "this_computer": False,
                      "host": "pc.tailnet.ts.net"}


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
