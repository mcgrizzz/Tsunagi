"""Recent requests for the settings page (backlog 6.4): memory only, no keys or bodies."""

import pytest
from access import key_required

from tsunagi.adapters import request_log


@pytest.fixture(autouse=True)
def empty_log():
    request_log.clear()
    yield
    request_log.clear()


def test_a_v1_request_is_recorded_without_its_query_string(client, reset_settings):
    reset_settings.update(**key_required("secret-key", name="Yomitan"))
    client.get("/v1/decks?api_key=secret-key", headers={"X-Api-Key": "secret-key", "Origin": "http://localhost"})
    [e] = request_log.recent()
    assert (e["method"], e["path"], e["status"]) == ("GET", "/v1/decks", 200)
    assert (e["app"], e["origin"], e["local"], e["client"]) == ("Yomitan", "http://localhost", True, "app:Yomitan")
    assert e["ms"] >= 0
    assert "secret-key" not in repr(e)


def test_keyed_requests_that_skip_the_key_check_are_still_listed_under_their_app(client, reset_settings):
    reset_settings.update(**key_required("kk", name="Phone"), allowed_hosts=["pc.example.ts.net"])
    remote = {"X-Api-Key": "kk", "Host": "pc.example.ts.net", "Tailscale-User-Login": "me@example.com"}
    client.get("/v1/health", headers=remote)  # no key check on this path
    client.get("/v1/decks", headers={**remote, "Host": "other.example"})  # refused by the Host check
    client.get("/v1/health", headers={"Host": "pc.example.ts.net", "Tailscale-User-Login": "me@example.com"})
    keyless, refused, health = request_log.recent()
    assert (health["path"], health["status"], health["client"]) == ("/v1/health", 200, "app:Phone")
    assert (refused["status"], refused["client"]) == (403, "app:Phone")
    assert keyless["client"] == "nokey:No key, other devices"


def test_requests_refused_before_auth_are_recorded(client):
    client.get("/v1/decks", headers={"Host": "evil.example:7777"})
    [e] = request_log.recent()
    assert e["status"] == 403 and e["client"] == "nokey:No key, other devices"


def test_ankiconnect_requests_record_the_action_and_its_error(client, reset_settings):
    reset_settings.update(**key_required("k"))
    client.post("/", json={"action": "deckNames", "version": 6, "key": "k"})
    client.post("/", json={"action": "deckNames", "version": 6})
    denied, ok = request_log.recent()  # newest first
    assert (ok["action"], ok["app"], ok["error"]) == ("deckNames", "Test app", None)
    assert (denied["action"], denied["status"]) == ("deckNames", 200)
    assert denied["app"] == "No key, this computer" and "api key" in denied["error"]
    assert "\"k\"" not in repr(denied) and "'k'" not in repr(ok)


def entry(t, app=None, origin=None, local=True, status=200, error=None, path="/v1/decks"):
    return {"time": t, "method": "GET", "path": path, "origin": origin, "local": local,
            "app": app, "action": None, "error": error, "status": status, "ms": 1.0}


def test_requests_are_grouped_by_app_then_origin_then_source():
    request_log.add(entry(1, app="Yomitan", origin="chrome-extension://abc"))
    request_log.add(entry(2, app="No key, this computer", origin="https://site.example"))
    request_log.add(entry(3, origin="https://site.example", status=403))  # refused before the key check
    request_log.add(entry(4, app="No key, other devices", local=False))
    request_log.add(entry(5))
    got = {c["id"]: (c["label"], c["kind"], c["requests"], c["failed"]) for c in request_log.clients()}
    assert got == {
        "app:Yomitan": ("Yomitan", "app", 1, 0),
        "origin:https://site.example": ("https://site.example", "website", 2, 1),
        "nokey:No key, other devices": ("No key, other devices", "no_key", 1, 0),
        "nokey:No key, this computer": ("No key, this computer", "no_key", 1, 0),
    }
    assert [c["id"] for c in request_log.clients()][0] == "nokey:No key, this computer"  # most recent first


def test_a_busy_client_cannot_push_out_another():
    request_log.add(entry(0, origin="https://rare.example", status=403))
    for i in range(1, 500):
        request_log.add(entry(i, app="Yomitan"))
    [rare] = request_log.recent("origin:https://rare.example")
    assert rare["status"] == 403
    assert len(request_log.recent("app:Yomitan")) == request_log.PER_CLIENT
    yomitan = next(c for c in request_log.clients() if c["label"] == "Yomitan")
    assert yomitan["requests"] == 499  # totals keep counting past the kept entries


def test_keyless_clients_are_capped_but_apps_are_never_dropped():
    request_log.add(entry(0, app="Yomitan"))
    for i in range(1, request_log.MAX_KEYLESS + 10):
        request_log.add(entry(i, origin=f"https://spam{i}.example"))
    ids = [c["id"] for c in request_log.clients()]
    assert "app:Yomitan" in ids
    assert len(ids) == request_log.MAX_KEYLESS + 1
    assert "origin:https://spam1.example" not in ids  # the one idle longest went first


def test_filters_and_the_shown_cap():
    request_log.add(entry(1, app="A", path="/v1/notes"))
    request_log.add(entry(2, app="B", status=401))
    request_log.add(entry(3, app="B", error="valid api key must be provided"))
    assert [e["time"] for e in request_log.recent()] == [3, 2, 1]
    assert [e["time"] for e in request_log.recent(failed_only=True)] == [3, 2]
    assert [e["time"] for e in request_log.recent(text="API KEY")] == [3]
    assert [e["time"] for e in request_log.recent(text="notes")] == [1]
    assert request_log.recent("app:gone") == []
    for i in range(request_log.MAX_SHOWN + 20):
        request_log.add(entry(10 + i, origin=f"https://o{i % 40}.example"))
    assert len(request_log.recent()) == request_log.MAX_SHOWN
