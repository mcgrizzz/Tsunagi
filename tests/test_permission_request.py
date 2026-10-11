"""POST /v1/permissions:request (6.26): a website asks for access natively, through
the same approval flow as AnkiConnect's requestPermission."""
import pytest

from tsunagi.adapters.config import DEFAULTS
from tsunagi.adapters.dialogs import PermissionDecision

ROUTE = "/v1/permissions:request"
SITE = "https://site.test"


@pytest.fixture()
def asked(monkeypatch, reset_settings):
    """The prompt's answers, and the websites it was shown for."""
    shown, answers = [], []

    def ask(origin):
        shown.append(origin)
        return answers.pop(0) if answers else PermissionDecision()

    monkeypatch.setattr("tsunagi.http.compat.ankiconnect._default_ask", ask)
    reset_settings.configure({**DEFAULTS, "cors_allowlist": []}, persist=None)
    return shown, answers, reset_settings


def request(client, origin=SITE, **headers):
    return client.post(ROUTE, headers={**({"Origin": origin} if origin else {}), **headers})


def test_a_new_website_is_asked_about_and_allowed(client, asked):
    shown, answers, settings = asked
    answers.append(PermissionDecision(accepted=True))
    resp = request(client)
    assert resp.status_code == 200 and resp.json() == {"permission": "granted",
                                                        "key_required": False}
    assert resp.headers["access-control-allow-origin"] == SITE
    assert shown == [SITE] and SITE in settings.get("cors_allowlist")
    assert client.get("/v1/decks", headers={"Origin": SITE}).status_code == 200


def test_a_website_not_allowed_is_denied_and_stays_out(client, asked):
    shown, _answers, _settings = asked
    assert request(client).json()["permission"] == "denied"
    assert client.get("/v1/decks", headers={"Origin": SITE}).status_code == 403


def test_dont_ask_again_ignores_the_website(client, asked):
    shown, answers, settings = asked
    answers.append(PermissionDecision(ignore=True))
    request(client)
    assert request(client).json()["permission"] == "denied"
    assert shown == [SITE] and settings.get("ankiconnect_ignore_origins") == [SITE]


def test_an_allowed_website_and_a_request_without_origin_are_not_asked_about(client, asked):
    shown, _answers, settings = asked
    settings.update(cors_allowlist=[SITE])
    assert request(client).json()["permission"] == "granted"
    assert request(client, origin=None).json()["permission"] == "granted"
    assert shown == []


def test_a_new_website_can_send_the_preflight(client, asked):
    resp = client.options(ROUTE, headers={"Origin": SITE, "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "content-type"})
    assert resp.status_code == 200 and resp.headers["access-control-allow-origin"] == SITE


def test_other_routes_still_refuse_a_new_website(client, asked):
    assert client.post("/v1/notes:delete", json={"note_ids": []},
                       headers={"Origin": SITE}).status_code == 403


def test_key_required_when_requests_without_a_key_have_no_access(client, asked):
    _shown, _answers, settings = asked
    settings.update(cors_allowlist=[SITE], no_key_local_role="none")
    assert request(client).json() == {"permission": "granted", "key_required": True}
