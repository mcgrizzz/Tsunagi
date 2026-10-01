"""A name another item has, ignoring case, is a 400 on create and rename (backlog 6.65).

Anki keeps these names unique ignoring case and, on a clash, renames silently
(`Front+`, `Card 1+`, `Default+`, `Basic-93af0`) or keeps both (presets).
"""
import pytest

MODEL = {"name": "Vocab", "fields": [{"name": "Word"}, {"name": "Meaning"}],
         "templates": [{"name": "Card 1", "qfmt": "{{Word}}", "afmt": "{{Meaning}}"},
                       {"name": "Card 2", "qfmt": "{{Meaning}}", "afmt": "{{Word}}"}]}


@pytest.fixture()
def mid(client, col):
    return client.post("/v1/models", json=MODEL).json()["result"]["id"]


def refused(response, message):
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == message


def test_fields(client, col, mid):
    names = lambda: [f["name"] for f in col.models.get(mid)["flds"]]
    refused(client.post(f"/v1/models/{mid}/fields", json={"name": "word"}), "Field name 'word' already exists")
    refused(client.patch(f"/v1/models/{mid}/fields/Meaning", json={"name": "Word"}), "Field name 'Word' already exists")
    assert names() == ["Word", "Meaning"]
    assert client.patch(f"/v1/models/{mid}/fields/Meaning", json={"name": "meaning"}).status_code == 200
    assert names() == ["Word", "meaning"]   # a change of case alone is the same field


def test_templates(client, col, mid):
    names = lambda: [t["name"] for t in col.models.get(mid)["tmpls"]]
    refused(client.post(f"/v1/models/{mid}/templates", json={"name": "card 1", "qfmt": "{{Word}}x", "afmt": "x"}),
            "Template name 'card 1' already exists")
    refused(client.patch(f"/v1/models/{mid}/templates/Card 2", json={"name": "Card 1"}),
            "Template name 'Card 1' already exists")
    assert names() == ["Card 1", "Card 2"]


def test_note_types(client, col, mid):
    refused(client.post("/v1/models", json={**MODEL, "name": "vocab"}), "Model name 'vocab' already exists")
    refused(client.patch(f"/v1/models/{mid}", json={"name": "Basic"}), "Model name 'Basic' already exists")
    assert col.models.get(mid)["name"] == "Vocab"
    refused(client.post("/v1/models", json={**MODEL, "name": "Other",
                                            "fields": [{"name": "A"}, {"name": "a"}]}), "Field name 'a' already exists")
    assert col.models.by_name("Other") is None


def test_decks(client, col):
    did = client.post("/v1/decks", json={"name": "Mining"}).json()["result"]["id"]
    refused(client.patch(f"/v1/decks/{did}", json={"name": "default"}), "Deck name 'default' already exists")
    assert col.decks.name(did) == "Mining"
    assert client.patch(f"/v1/decks/{did}", json={"name": "mining"}).status_code == 200


def test_presets(client, col):
    pid = client.post("/v1/deck-configs", json={"name": "Light"}).json()["result"]["id"]
    refused(client.post("/v1/deck-configs", json={"name": "light"}), "Preset name 'light' already exists")
    refused(client.patch(f"/v1/deck-configs/{pid}", json={"name": "Default"}), "Preset name 'Default' already exists")
    assert sorted(c["name"] for c in col.decks.all_config()) == ["Default", "Light"]
    assert client.patch(f"/v1/deck-configs/{pid}", json={"name": "LIGHT"}).status_code == 200
