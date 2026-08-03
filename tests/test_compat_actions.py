"""
Wire-shape golden tests for the Tier-1 compat actions, against the fake
collection seed (models: Basic/Cloze; decks: Default).
"""
from tsunagi.http.compat import actions  # noqa: F401  (ensure handlers are registered)
from tsunagi.http.compat.errors import MODEL_NOT_FOUND


def rpc(client, action, params=None, version=6):
    body = {"action": action, "version": version}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


class TestMisc:
    def test_version(self, client):
        assert rpc(client, "version") == {"result": 6, "error": None}


class TestDeckActions:
    def test_deck_names(self, client):
        assert rpc(client, "deckNames") == {"result": ["Default"], "error": None}

    def test_deck_names_and_ids(self, client):
        assert rpc(client, "deckNamesAndIds") == {"result": {"Default": 1}, "error": None}

    def test_create_deck_returns_int_id(self, client):
        resp = rpc(client, "createDeck", {"deck": "Japanese"})
        assert resp["error"] is None
        assert isinstance(resp["result"], int)
        assert "Japanese" in rpc(client, "deckNames")["result"]

    def test_create_deck_existing_returns_same_id_no_error(self, client):
        first = rpc(client, "createDeck", {"deck": "Japanese"})
        second = rpc(client, "createDeck", {"deck": "Japanese"})
        assert second == {"result": first["result"], "error": None}

    def test_create_nested_deck_creates_parents(self, client):
        rpc(client, "createDeck", {"deck": "Languages::Japanese"})
        names = rpc(client, "deckNames")["result"]
        assert "Languages" in names
        assert "Languages::Japanese" in names


class TestModelActions:
    def test_model_names(self, client):
        names = rpc(client, "modelNames")["result"]
        # A real collection ships six stock notetypes.
        assert {"Basic", "Cloze"} <= set(names)

    def test_model_names_and_ids(self, client):
        by_name = rpc(client, "modelNamesAndIds")["result"]
        assert {"Basic", "Cloze"} <= set(by_name)
        assert all(isinstance(v, int) for v in by_name.values())

    def test_model_field_names(self, client):
        resp = rpc(client, "modelFieldNames", {"modelName": "Basic"})
        assert resp == {"result": ["Front", "Back"], "error": None}

    def test_model_field_names_missing_exact_error(self, client):
        resp = rpc(client, "modelFieldNames", {"modelName": "Nope"})
        assert resp == {"result": None, "error": MODEL_NOT_FOUND.format("Nope")}

    def test_find_models_by_name(self, client):
        resp = rpc(client, "findModelsByName", {"modelNames": ["Basic"]})
        assert resp["error"] is None
        (model,) = resp["result"]
        # Anki wire names (by_alias), not our human names
        assert model["name"] == "Basic"
        assert [f["name"] for f in model["flds"]] == ["Front", "Back"]
        assert "tmpls" in model and "sortf" in model

    def test_find_models_by_name_missing_exact_error(self, client):
        resp = rpc(client, "findModelsByName", {"modelNames": ["Basic", "Nope"]})
        assert resp == {"result": None, "error": MODEL_NOT_FOUND.format("Nope")}

    def test_find_models_by_id(self, client):
        cloze_id = rpc(client, "modelNamesAndIds")["result"]["Cloze"]
        resp = rpc(client, "findModelsById", {"modelIds": [cloze_id]})
        assert resp["error"] is None
        assert resp["result"][0]["name"] == "Cloze"

    def test_find_models_by_id_missing_exact_error(self, client):
        resp = rpc(client, "findModelsById", {"modelIds": [9999]})
        assert resp == {"result": None, "error": MODEL_NOT_FOUND.format(9999)}
