"""POST /v1/permissions:request (6.26, 6.124): a website or program asks, you choose
a role, and if you allow it, it becomes an app and gets its key in the answer."""
import threading

import pytest

from tsunagi.adapters.access_requests import AccessDecision
from tsunagi.adapters.config import DEFAULTS

ROUTE = "/v1/permissions:request"
SITE = "https://site.test"


@pytest.fixture()
def prompt(monkeypatch, reset_settings):
    """The prompts shown (AccessAsk), and the answers to give them in turn."""
    shown, answers = [], []

    def ask(request):
        shown.append(request)
        return answers.pop(0) if answers else AccessDecision()

    monkeypatch.setattr("tsunagi.http.v1.permissions._ask", ask)
    reset_settings.configure({**DEFAULTS, "cors_allowlist": []}, persist=None)
    return shown, answers, reset_settings


def ask_access(client, origin=SITE, body=None, **kwargs):
    headers = {"Origin": origin} if origin else {}
    return client.post(ROUTE, json=body, headers=headers, **kwargs)


def allow(role="default"):
    return AccessDecision(accepted=True, role=role)


def test_an_allowed_website_becomes_an_app_and_gets_its_key(client, prompt):
    shown, answers, settings = prompt
    answers.append(allow())
    body = ask_access(client).json()
    assert (body["permission"], body["app"], body["role"]) == ("granted", "site.test", "Default")
    [request] = shown
    assert (request.origin, request.name, request.existing, request.role) == (SITE, "site.test", None, "default")
    assert ("read_only", "Read-only") in request.roles and all(rid != "none" for rid, _ in request.roles)
    [app] = settings.get("apps")
    assert app == {"name": "site.test", "key": body["key"], "role": "default", "origin": SITE}
    assert settings.get("cors_allowlist") == []
    me = client.get("/v1/health", headers={"Origin": SITE, "X-Api-Key": body["key"]}).json()["caller"]
    assert (me["name"], me["key"]) == ("site.test", "valid")


def test_the_role_chosen_applies(client, prompt):
    _shown, answers, _settings = prompt
    answers.append(allow("read_only"))
    key = ask_access(client).json()["key"]
    headers = {"Origin": SITE, "X-Api-Key": key}
    assert client.get("/v1/decks", headers=headers).status_code == 200
    assert client.post("/v1/decks", json={"name": "x"}, headers=headers).status_code == 403


def test_a_suggested_name_and_role_are_preselected(client, prompt):
    shown, _answers, _settings = prompt
    ask_access(client, body={"name": "Mining helper", "role": "Read-only"})
    assert (shown[0].name, shown[0].role) == ("Mining helper", "read_only")


def test_a_website_not_allowed_gets_nothing(client, prompt):
    _shown, _answers, settings = prompt
    assert ask_access(client).json() == {"permission": "denied", "key": None, "app": None,
                                         "role": None, "key_required": False}
    assert settings.get("apps") == []
    assert client.get("/v1/decks", headers={"Origin": SITE}).status_code == 403


def test_dont_ask_again_ignores_the_website(client, prompt):
    shown, answers, settings = prompt
    answers.append(AccessDecision(ignore=True))
    ask_access(client)
    assert ask_access(client).json()["permission"] == "denied"
    assert len(shown) == 1 and settings.get("ankiconnect_ignore_origins") == [SITE]


def test_asking_again_asks_and_gives_the_same_app_a_new_key(client, prompt, reset_settings):
    shown, answers, settings = prompt
    answers.extend([allow(), allow("read_only")])
    old = ask_access(client).json()["key"]
    new = ask_access(client).json()
    assert shown[1].existing == ("site.test", "Default")
    [app] = settings.get("apps")
    assert app["key"] == new["key"] != old and app["role"] == "read_only"
    reset_settings.update(no_key_local_role="none")
    assert client.get("/v1/decks", headers={"X-Api-Key": old}).status_code == 401


def test_turning_its_app_off_cuts_the_website_off(client, prompt):
    _shown, answers, settings = prompt
    answers.append(allow())
    key = ask_access(client).json()["key"]
    settings.update(apps=[{**settings.get("apps")[0], "enabled": False}])
    assert client.get("/v1/decks", headers={"Origin": SITE, "X-Api-Key": key}).status_code == 403


def test_a_program_asks_by_name_and_is_matched_by_it(client, prompt):
    shown, answers, settings = prompt
    answers.extend([allow(), allow()])
    first = ask_access(client, origin=None, body={"name": "Yomine"}).json()
    assert (shown[0].origin, shown[0].name, shown[0].address) == (None, "Yomine", None)
    again = ask_access(client, origin=None, body={"name": "Yomine"}).json()
    assert shown[1].existing == ("Yomine", "Default")
    [app] = settings.get("apps")
    assert "origin" not in app and app["key"] == again["key"] != first["key"]


def test_a_program_without_a_name_and_dont_ask_again(client, prompt):
    shown, answers, settings = prompt
    answers.append(AccessDecision(ignore=True))
    ask_access(client, origin=None)
    assert shown[0].name == "Program on this computer"
    assert ask_access(client, origin=None).json()["permission"] == "denied" and len(shown) == 1
    assert settings.get("ignored_programs") == ["Program on this computer"]


def test_another_device_is_shown_by_its_address(prompt):
    from fastapi.testclient import TestClient

    from tsunagi.app import app
    shown, _answers, _settings = prompt
    with TestClient(app, base_url="http://127.0.0.1", client=("192.168.1.5", 50000)) as remote:
        assert remote.post(ROUTE, json={"name": "Phone"}).status_code == 200
    assert (shown[0].name, shown[0].address) == ("Phone", "192.168.1.5")


def test_a_website_named_like_an_existing_app_gets_a_free_name(client, prompt):
    _shown, answers, settings = prompt
    settings.update(apps=[{"name": "site.test", "key": "k1", "role": "default"}])
    answers.append(allow())
    assert ask_access(client).json()["app"] == "site.test (2)"
    assert len(settings.get("apps")) == 2


def test_one_prompt_at_a_time_and_every_waiting_request_gets_its_answer(client, prompt, monkeypatch):
    shown = []
    release = threading.Event()

    def slow(request):
        shown.append(request)
        release.wait(5)
        return allow()
    monkeypatch.setattr("tsunagi.http.v1.permissions._ask", slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(ask_access(client).json()))
               for _ in range(2)]
    for t in threads:
        t.start()
    while not shown:
        threading.Event().wait(0.01)
    threading.Event().wait(0.2)  # the second request is waiting by now
    release.set()
    for t in threads:
        t.join(5)
    assert len(shown) == 1 and results[0]["key"] == results[1]["key"]


def test_anki_pages_are_denied_without_asking(client, prompt):
    shown, _answers, settings = prompt
    settings.anki_page_origin = "http://127.0.0.1:40000"
    try:
        assert ask_access(client, origin="http://127.0.0.1:40000").json()["permission"] == "denied"
    finally:
        settings.anki_page_origin = None
    assert shown == []


def test_a_new_website_can_send_the_preflight(client, prompt):
    resp = client.options(ROUTE, headers={"Origin": SITE, "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "content-type"})
    assert resp.status_code == 200 and resp.headers["access-control-allow-origin"] == SITE


def test_other_routes_still_refuse_a_new_website(client, prompt):
    assert client.post("/v1/notes:delete", json={"note_ids": []},
                       headers={"Origin": SITE}).status_code == 403


def test_ankiconnect_request_permission_gives_no_key(client, prompt, monkeypatch):
    """The Shim stays AnkiConnect's: allowing adds the site, which then calls keyless."""
    _shown, _answers, settings = prompt
    monkeypatch.setattr("tsunagi.http.compat.ankiconnect._default_ask", lambda origin: True)
    resp = client.post("/", json={"action": "requestPermission", "version": 6}, headers={"Origin": SITE})
    assert resp.json()["result"]["permission"] == "granted" and "key" not in resp.json()["result"]
    assert settings.get("cors_allowlist") == [SITE] and settings.get("apps") == []


@pytest.mark.parametrize("body", [{"role": []}, {"name": {}}, {"key": "mine"}])
def test_a_malformed_request_is_422_without_asking(client, prompt, body):
    shown, _answers, _settings = prompt
    assert ask_access(client, body=body).status_code == 422 and shown == []
