"""
Dispatcher-level tests for the compat key/origin gate and requestPermission.
The Qt dialog is replaced by an injected fake; no aqt involved.

All calls here use version 6, so successful replies are {"result","error"}
envelopes (version semantics themselves are covered in test_compat_dispatcher).
"""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tsunagi.adapters.settings import Settings
from tsunagi.http.compat.ankiconnect import (
    API_KEY_ERROR,
    handle_ankiconnect_rpc,
    origin_allowed_for,
)
from tsunagi.http.compat.registry import registry

ORIGIN = "https://allowed.test"
OTHER = "https://unknown.test"

@pytest.fixture(autouse=True, scope="module")
def _test_echo_action():
    """
    A stand-in action for the gate tests, added for this module only.

    It used to be registered at import and left there, which leaked a
    non-existent action into the global registry - test_parity_doc.py then saw
    'testEcho' as implemented and failed depending on test order.
    """
    registry.register("testEcho")(lambda params: {"echo": params or None})
    yield
    registry._handlers.pop("testEcho", None)   # our mess, our cleanup


def rpc(action, settings, origin=None, key=None, ask=None):
    raw = {"action": action, "version": 6}
    if key is not None:
        raw["key"] = key
    return handle_ankiconnect_rpc(raw, origin=origin, settings=settings, ask_permission=ask)


class TestRequestPermission:
    def test_no_origin_granted_without_dialog(self):
        calls = []
        resp = rpc("requestPermission", Settings({"api_key": ""}), ask=lambda o: calls.append(o))
        assert resp["result"] == {"permission": "granted", "requireApikey": False, "version": 6}
        assert calls == []

    def test_allowed_origin_granted_without_dialog(self):
        calls = []
        s = Settings({"api_key": "k", "cors_allowlist": [ORIGIN]})
        resp = rpc("requestPermission", s, origin=ORIGIN, ask=lambda o: calls.append(o))
        assert resp["result"] == {"permission": "granted", "requireApikey": True, "version": 6}
        assert calls == []

    def test_unknown_origin_accept_persists(self):
        persisted = []
        s = Settings({"api_key": "", "cors_allowlist": []}, persist=persisted.append)
        resp = rpc("requestPermission", s, origin=OTHER, ask=lambda o: True)
        assert resp["result"]["permission"] == "granted"
        assert s.is_origin_allowed(OTHER)
        assert persisted and OTHER in persisted[-1]["cors_allowlist"]

    def test_unknown_origin_deny_not_persisted(self):
        s = Settings({"api_key": "", "cors_allowlist": []})
        resp = rpc("requestPermission", s, origin=OTHER, ask=lambda o: False)
        assert resp["result"] == {"permission": "denied"}
        assert not s.is_origin_allowed(OTHER)

    def test_works_even_when_key_configured_and_absent(self):
        # requestPermission is exempt from the key gate
        resp = rpc("requestPermission", Settings({"api_key": "k"}))
        assert resp["error"] is None
        assert resp["result"]["permission"] == "granted"


class TestKeyGate:
    def test_no_key_configured_dispatches(self):
        resp = rpc("testEcho", Settings({"api_key": ""}))
        assert resp["error"] is None

    def test_missing_key_canonical_error(self):
        resp = rpc("testEcho", Settings({"api_key": "k"}))
        assert resp["result"] is None
        assert resp["error"] == API_KEY_ERROR

    def test_wrong_key_canonical_error(self):
        resp = rpc("testEcho", Settings({"api_key": "k"}), key="wrong")
        assert resp["error"] == API_KEY_ERROR

    def test_correct_key_dispatches(self):
        resp = rpc("testEcho", Settings({"api_key": "k"}), key="k")
        assert resp["error"] is None
        assert resp["result"] == {"echo": None}


class TestOriginGate:
    """
    Origin enforcement is HTTP-layer (403), matching AnkiConnect - see
    origin_allowed_for. The dispatcher itself no longer inspects origins
    except for requestPermission.
    """

    def test_no_origin_allowed(self):
        assert origin_allowed_for("testEcho", None, Settings({"cors_allowlist": []}))

    def test_unknown_origin_blocked(self):
        assert not origin_allowed_for("testEcho", OTHER, Settings({"cors_allowlist": []}))

    def test_allowed_origin_passes(self):
        s = Settings({"cors_allowlist": [ORIGIN]})
        assert origin_allowed_for("testEcho", ORIGIN, s)

    def test_request_permission_always_passes(self):
        s = Settings({"cors_allowlist": []})
        assert origin_allowed_for("requestPermission", OTHER, s)


class TestEnvelopeOverHttp:
    """One pass through real endpoint wiring: HTTP 200 + JSON envelope."""

    @pytest.fixture()
    def client(self):
        s = Settings({"api_key": "k", "cors_allowlist": []})
        app = FastAPI()

        @app.post("/")
        def endpoint(body: dict, request: Request):
            return handle_ankiconnect_rpc(
                body, origin=request.headers.get("origin"),
                settings=s, ask_permission=lambda o: False,
            )

        return TestClient(app)

    def test_missing_key_is_http_200_with_error_envelope(self, client):
        resp = client.post("/", json={"action": "testEcho", "version": 6})
        assert resp.status_code == 200
        assert resp.json() == {"result": None, "error": API_KEY_ERROR}

    def test_request_permission_denied_envelope(self, client):
        resp = client.post("/", json={"action": "requestPermission", "version": 6},
                           headers={"Origin": OTHER})
        assert resp.status_code == 200
        assert resp.json() == {"result": {"permission": "denied"}, "error": None}
