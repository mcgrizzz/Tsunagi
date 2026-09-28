"""Native discovery reports the routes clients can call and their restrictions."""
import pytest
from access import key_required


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
def test_permissions_apply_to_the_operation_or_its_option(client, reset_settings, enabled):
    reset_settings.update(no_key_local_role="everything" if enabled else "default")
    operations = report(client)["operations"]
    memory = operations["POST /v1/cards:set-memory-state"]
    media = operations["POST /v1/media"]
    assert memory["status"] == ("available" if enabled else "disabled")
    assert memory["setting"] == "permissions.memory_state"
    assert media["status"] == "available"
    assert media["options"]["path"]["status"] == ("available" if enabled else "disabled")
    assert media["options"]["path"]["setting"] == "permissions.local_files"
    if memory["options"]["cards[].decay"]["status"] != "unsupported":
        assert memory["options"]["cards[].decay"]["status"] == memory["status"]
    if not enabled:
        assert "does not allow memory_state" in memory["reason"]
        response = client.post("/v1/media", json={"filename": "probe", "path": "/missing"})
        assert response.status_code == 200
        assert response.json()["created"] == []
        assert response.json()["failed"][0]["code"] == "invalid_media"
        assert "disabled" in response.text


def test_role_change_is_visible_without_restarting(client, reset_settings):
    assert report(client)["operations"]["POST /v1/cards:set-memory-state"]["status"] == "disabled"
    reset_settings.update(no_key_local_role="everything")
    assert report(client)["operations"]["POST /v1/cards:set-memory-state"]["status"] == "available"


def test_version_options_are_available_on_supported_anki(client, reset_settings):
    reset_settings.update(no_key_local_role="everything")
    operations = report(client)["operations"]
    decay = operations["POST /v1/cards:set-memory-state"]["options"]["cards[].decay"]
    assert decay["status"] == "available"
    retention = operations["PATCH /v1/decks/{id}"]["options"]["desired_retention"]
    assert retention["status"] == "available"


def test_discovery_does_not_expose_keys_or_change_collection(client, col, reset_settings):
    before = col.undo_status()
    reset_settings.update(**key_required("private-discovery-key"),
                          cors_allowlist=["https://private-origin.test"])
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


def test_capabilities_say_who_the_caller_was_taken_to_be(client):
    caller = client.get("/v1/capabilities").json()["caller"]
    assert caller == {"name": "No key, this computer", "role": "Default (like AnkiConnect)",
                      "this_computer": True, "host": "127.0.0.1"}
