"""
Full-app tests for /v1/deck-configs over the fake collection.
"""


class TestReads:
    def test_list_includes_the_default(self, client):
        body = client.get("/v1/deck-configs").json()
        assert [c["id"] for c in body["items"]] == [1]
        assert body["items"][0]["name"] == "Default"

    def test_nested_scheduler_keys_survive(self, client):
        conf = client.get("/v1/deck-configs").json()["items"][0]
        # Passed through untyped on purpose - a schema would drop unknown keys.
        assert conf["new"]["perDay"] == 20
        assert conf["rev"]["perDay"] == 200

    def test_select_into_nested_config(self, client):
        body = client.get("/v1/deck-configs", params={
            "select": "id,name", "shape": "object"}).json()
        assert body["items"] == [{"id": 1, "name": "Default"}]

    def test_id_index(self, client):
        body = client.get("/v1/deck-configs", params={"where": "id==1"}).json()
        assert [c["name"] for c in body["items"]] == ["Default"]

    def test_where_on_nested_value(self, client):
        assert client.get("/v1/deck-configs", params={
            "where": "name==Default"}).json()["items"]


class TestMutations:
    def _create(self, client, name="Cram", clone=None):
        payload = {"name": name}
        if clone is not None:
            payload["clone_from_id"] = clone
        return client.post("/v1/deck-configs", json=payload)

    def test_create_clones_the_default(self, client):
        resp = self._create(client, clone=1)
        assert resp.status_code == 201
        conf = resp.json()["result"]
        assert conf["name"] == "Cram" and conf["id"] != 1
        assert conf["new"]["perDay"] == 20  # inherited from the clone source

    def test_create_without_clone(self, client):
        conf = self._create(client).json()["result"]
        assert conf["name"] == "Cram" and conf["id"] != 1

    def test_create_requires_a_name(self, client):
        assert client.post("/v1/deck-configs", json={"name": " "}).status_code == 400

    def test_create_unknown_clone_source_is_404(self, client):
        assert self._create(client, clone=999999).status_code == 404

    def test_patch_merges_nested_keys(self, client):
        cid = self._create(client, clone=1).json()["result"]["id"]
        conf = client.patch(f"/v1/deck-configs/{cid}",
                            json={"new": {"perDay": 40}}).json()["result"]
        assert conf["new"]["perDay"] == 40
        assert conf["new"]["initialFactor"] == 2500   # sibling keys preserved
        assert conf["rev"]["perDay"] == 200           # other groups untouched

    def test_patch_cannot_move_the_id(self, client):
        cid = self._create(client, clone=1).json()["result"]["id"]
        conf = client.patch(f"/v1/deck-configs/{cid}",
                            json={"id": 12345, "name": "Renamed"}).json()["result"]
        assert conf["id"] == cid and conf["name"] == "Renamed"

    def test_patch_missing_is_404(self, client):
        assert client.patch("/v1/deck-configs/999999", json={"name": "x"}).status_code == 404

    def test_delete(self, client):
        cid = self._create(client, clone=1).json()["result"]["id"]
        assert client.delete(f"/v1/deck-configs/{cid}").json()["success"] is True
        assert [c["id"] for c in client.get("/v1/deck-configs").json()["items"]] == [1]

    def test_delete_reassigns_decks_to_the_default(self, client):
        cid = self._create(client, clone=1).json()["result"]["id"]
        client.post("/v1/decks", json={"name": "JP"})
        did = [d["id"] for d in client.get("/v1/decks").json()["items"]
               if d["name"] == "JP"][0]
        client.patch(f"/v1/decks/{did}", json={"config_id": cid})

        client.delete(f"/v1/deck-configs/{cid}")
        deck = client.get("/v1/decks", params={"where": f"id=={did}"}).json()["items"][0]
        assert deck["config_id"] == 1  # Anki never leaves a deck pointing at nothing

    def test_delete_default_is_400(self, client):
        resp = client.delete("/v1/deck-configs/1")
        assert resp.status_code == 400
        assert "default" in resp.json()["detail"].lower()

    def test_delete_missing_is_404(self, client):
        assert client.delete("/v1/deck-configs/999999").status_code == 404


class TestAssignment:
    def test_deck_patch_assigns_a_config(self, client):
        cid = client.post("/v1/deck-configs",
                          json={"name": "Cram", "clone_from_id": 1}).json()["result"]["id"]
        client.post("/v1/decks", json={"name": "JP"})
        did = [d["id"] for d in client.get("/v1/decks").json()["items"]
               if d["name"] == "JP"][0]
        # No separate endpoint: assignment is a property of the deck.
        deck = client.patch(f"/v1/decks/{did}", json={"config_id": cid}).json()["result"]
        assert deck["config_id"] == cid
