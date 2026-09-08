"""Shim binding must reject requests before collection or permission effects."""

from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc


def test_missing_model_name_cannot_trigger_all_model_saves(col, client):
    before = {m["id"]: m["usn"] for m in col.models.all()}
    reply = client.post("/", json={
        "action": "findAndReplaceInModels", "version": 6,
        "params": {"findText": "not present", "replaceText": "replacement"},
    }).json()
    assert reply == {"result": None, "error": (
        "AnkiConnect.findAndReplaceInModels() missing 1 required positional argument: 'modelName'")}
    col.models._clear_cache()
    assert {m["id"]: m["usn"] for m in col.models.all()} == before


def test_extra_argument_prevents_nested_deck_deletion(col, client):
    did = col.decks.id("Binding fixture")
    reply = client.post("/", json={
        "action": "multi", "version": 6, "params": {"actions": [{
            "action": "deleteDecks", "version": 6,
            "params": {"decks": ["Binding fixture"], "cardsToo": True, "unexpected": True},
        }]},
    }).json()
    assert reply == {"error": None, "result": [{"result": None, "error": (
        "AnkiConnect.deleteDecks() got an unexpected keyword argument 'unexpected'")}]}
    assert col.decks.by_name("Binding fixture")["id"] == did


def test_permission_binding_rejects_before_prompt():
    prompts = []
    reply = handle_ankiconnect_rpc(
        {"action": "requestPermission", "version": 6, "params": {"unexpected": True}},
        origin="https://unknown.example", settings={},
        ask_permission=lambda origin: prompts.append(origin),
    )
    assert reply == {"result": None, "error": (
        "AnkiConnect.requestPermission() got an unexpected keyword argument 'unexpected'")}
    assert prompts == []


def test_permission_client_values_cannot_override_origin_gate(reset_settings):
    prompts = []

    def deny(origin):
        prompts.append(origin)
        return False

    reply = handle_ankiconnect_rpc(
        {"action": "requestPermission", "version": 6,
         "params": {"origin": "http://localhost", "allowed": True}},
        origin="https://unknown.example", ask_permission=deny,
    )
    assert reply == {"result": {"permission": "denied"}, "error": None}
    assert prompts == ["https://unknown.example"]
