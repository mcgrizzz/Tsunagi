"""Anki's own pages run card-template JavaScript; they stay out unless the user opts in."""
import pytest

ANKI_PAGE = "http://127.0.0.1:34083"
NOTE = {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "from a card", "Back": "x"}}


@pytest.fixture(autouse=True)
def anki_page(reset_settings, monkeypatch):
    monkeypatch.setattr(reset_settings, "anki_page_origin", ANKI_PAGE)
    return reset_settings


def created(col):
    return len(col.find_notes('"Front:from a card"'))


def test_card_script_cannot_use_either_api(client, col):
    headers = {"Origin": ANKI_PAGE}
    assert client.post("/v1/notes", json=NOTE, headers=headers).status_code == 403
    rpc = {"action": "addNote", "version": 6, "params": {"note": {**NOTE, "deckName": "Default"}}}
    assert client.post("/", json=rpc, headers=headers).status_code == 403
    assert created(col) == 0


def test_card_script_cannot_prompt_for_permission(client, monkeypatch):
    from tsunagi.http.compat import ankiconnect

    prompts = []
    monkeypatch.setattr(ankiconnect, "_default_ask", lambda origin: prompts.append(origin) or True)
    reply = client.post("/", json={"action": "requestPermission", "version": 6},
                        headers={"Origin": ANKI_PAGE}).json()
    assert reply["result"] == {"permission": "denied"}
    assert prompts == []


def test_allow_all_does_not_include_anki_pages(client, anki_page):
    anki_page.update(cors_allowlist=["*"])
    assert client.post("/v1/notes", json=NOTE, headers={"Origin": ANKI_PAGE}).status_code == 403


def test_the_gate_lets_anki_pages_in(client, col, anki_page):
    anki_page.update(gates={**anki_page.get("gates"), "anki_page_scripts": True})
    assert client.post("/v1/notes", json=NOTE, headers={"Origin": ANKI_PAGE}).status_code == 200
    assert created(col) == 1


def test_other_local_pages_keep_working(client, col):
    response = client.post("/v1/notes", json=NOTE, headers={"Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 200
    assert created(col) == 1
