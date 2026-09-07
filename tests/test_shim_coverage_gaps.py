"""Behavioral cases missing from the action execution inventory.

Reference: anki-connect de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e,
plugin/__init__.py: apiReflect, deckNameFromId, modelTemplateRemove.
"""

import pytest

from tsunagi.http.compat.registry import registry


def rpc(client, action, **params):
    response = client.post("/", json={"action": action, "version": 6, "params": params})
    assert response.status_code == 200
    return response.json()


def test_reflect_lists_the_complete_dispatch_surface(client):
    response = rpc(client, "apiReflect", scopes=["actions"])
    assert response["error"] is None
    result = response["result"]
    assert result["scopes"] == ["actions"]
    assert result["actions"] == sorted(set(registry.list_actions()) | {"multi", "requestPermission"})


def test_reflect_preserves_requested_order_and_duplicates(client):
    assert rpc(client, "apiReflect", scopes=["unknown", "actions"],
               actions=["version", "notAnAction", "multi", "version"]) == {
        "result": {"scopes": ["actions"], "actions": ["version", "multi", "version"]},
        "error": None,
    }


def test_reflect_without_action_scope(client):
    assert rpc(client, "apiReflect", scopes=["unknown"]) == {
        "result": {"scopes": []}, "error": None,
    }


@pytest.mark.parametrize("params,message", [
    ({}, "scopes has invalid value"),
    ({"scopes": None}, "scopes has invalid value"),
    ({"scopes": "actions"}, "scopes has invalid value"),
    ({"scopes": [], "actions": "version"}, "actions has invalid value"),
    ({"scopes": ["actions"], "actions": [1]}, "attribute name must be string, not 'int'"),
])
def test_reflect_invalid_parameter_errors(client, params, message):
    assert rpc(client, "apiReflect", **params) == {"result": None, "error": message}


def test_deck_name_from_id(client, col):
    deck_id = col.decks.id("Parent::Child")
    assert rpc(client, "deckNameFromId", deckId=deck_id) == {
        "result": "Parent::Child", "error": None,
    }


def test_template_remove_persists_and_renumbers_remaining_templates(client, col):
    result = rpc(client, "createModel", modelName="Shim coverage model",
                 inOrderFields=["Front", "Back"], cardTemplates=[
                     {"Name": "Forward", "Front": "{{Front}}", "Back": "{{Back}}"},
                     {"Name": "Reverse", "Front": "{{Back}}", "Back": "{{Front}}"},
                 ])
    assert result["error"] is None
    assert rpc(client, "modelTemplateRemove", modelName="Shim coverage model",
               templateName="Forward") == {"result": None, "error": None}
    model = col.models.by_name("Shim coverage model")
    assert [(t["name"], t["ord"]) for t in model["tmpls"]] == [("Reverse", 0)]
