"""Native discovery reports the routes clients can call and their restrictions."""
import pytest


def report(client):
    response = client.get("/v1/capabilities")
    assert response.status_code == 200, response.text
    return response.json()


def test_catalog_matches_native_openapi_and_excludes_compat(client):
    schema = client.get("/openapi.json").json()
    expected = {
        f"{method.upper()} {path}": operation["operationId"]
        for path, methods in schema["paths"].items() if path.startswith("/v1/")
        for method, operation in methods.items() if "operationId" in operation
    }
    data = report(client)
    assert {key: value["operation_id"] for key, value in data["operations"].items()} == expected
    assert "POST /" not in data["operations"]
    assert "GET /actions" not in data["operations"]
    assert "fsrs" not in data
    assert data["operations"]["GET /v1/notes"]["status"] == "available"


@pytest.mark.parametrize("enabled", [False, True])
def test_settings_apply_to_the_operation_or_its_option(client, reset_settings, enabled):
    reset_settings.update(gates={"cards_set_memory_state": enabled, "media_allow_local_path": enabled})
    operations = report(client)["operations"]
    memory = operations["POST /v1/cards:set-memory-state"]
    media = operations["POST /v1/media"]
    assert memory["status"] == ("available" if enabled else "disabled")
    assert memory["setting"] == "gates.cards_set_memory_state"
    assert media["status"] == "available"
    assert media["options"]["path"]["status"] == ("available" if enabled else "disabled")
    assert media["options"]["path"]["setting"] == "gates.media_allow_local_path"
    if memory["options"]["cards[].decay"]["status"] != "unsupported":
        assert memory["options"]["cards[].decay"]["status"] == memory["status"]
    if not enabled:
        assert "disabled in settings" in memory["reason"]
        response = client.post("/v1/media", json={"filename": "probe", "path": "/missing"})
        assert response.status_code == 400
        assert "disabled" in response.text


def test_gate_change_is_visible_without_restarting(client, reset_settings):
    assert report(client)["operations"]["POST /v1/cards:set-memory-state"]["status"] == "disabled"
    reset_settings.update(gates={"cards_set_memory_state": True})
    assert report(client)["operations"]["POST /v1/cards:set-memory-state"]["status"] == "available"


def test_version_options_match_existing_anki_guards(client, reset_settings):
    from anki import cards_pb2

    from tsunagi.adapters.anki.decks import _retention_supported

    reset_settings.update(gates={"cards_set_memory_state": True})
    operations = report(client)["operations"]
    decay = operations["POST /v1/cards:set-memory-state"]["options"]["cards[].decay"]
    assert decay["status"] == ("available" if "decay" in cards_pb2.Card.DESCRIPTOR.fields_by_name else "unsupported")
    retention = operations["PATCH /v1/decks/{id}"]["options"]["desired_retention"]
    assert retention["status"] == ("available" if _retention_supported() else "unsupported")


def test_discovery_does_not_expose_keys_or_change_collection(client, col, reset_settings):
    before = col.undo_status()
    reset_settings.update(api_key="private-discovery-key", cors_allowlist=["https://private-origin.test"])
    response = client.get("/v1/capabilities", headers={"X-API-Key": "private-discovery-key"})
    assert response.status_code == 200, response.text
    assert "private-discovery-key" not in response.text
    assert "private-origin.test" not in response.text
    assert col.undo_status() == before
    assert client.get("/v1/capabilities").status_code == 401


def test_import_restrictions_are_in_the_same_report(client):
    expected = client.get("/v1/collection/import-options").json()["unsupported_options"]
    options = report(client)["operations"]["POST /v1/collection:import"]["options"]
    assert set(options) == set(expected)
    assert all(value["status"] == "unsupported" for value in options.values())
