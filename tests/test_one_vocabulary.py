"""The Tsunagi API names things as Anki's UI does, one name each (backlog 6.115).
The names it used before are gone; Anki's own column names stay accepted as aliases."""
import pytest

from tsunagi.shared.permissions import GRANTS


@pytest.mark.parametrize("path", ["/v1/models", "/v1/deck-configs"])
def test_the_old_resources_are_gone(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path,field", [
    ("/v1/notes", "model_name"), ("/v1/notes", "model_id"), ("/v1/cards", "model_name"),
    ("/v1/decks", "config_id"), ("/v1/reviews", "time_ms"), ("/v1/media", "mtime"),
])
def test_the_old_field_names_are_unknown(client, path, field):
    assert client.get(path, params={"select": field}).status_code == 400


@pytest.mark.parametrize("body", [
    {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "a"}},
    {"model_name": "Basic", "deckName": "Default", "fields": {"Front": "a"}},
    {"note_type_name": "Basic", "deckName": "Default", "fields": {"Front": "a"},
     "duplicateScopeOptions": {"checkAllModels": True}},
])
def test_note_bodies_refuse_the_old_names(client, col, body):
    assert client.post("/v1/notes", json=body).status_code == 422
    assert col.note_count() == 0


def test_answers_take_a_rating(client):
    assert client.post("/v1/cards:answer", json={"answers": [{"card_id": 1, "ease": 3}]}).status_code == 422


def test_permissions_use_the_new_names():
    assert {"read:note_types", "write:note_types", "read:deck_presets", "write:deck_presets"} <= GRANTS
    assert not {"models", "deck_configs"} & {g.split(":", 1)[-1] for g in GRANTS}
