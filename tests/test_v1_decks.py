"""
Full-app tests for the /v1/decks resource over the fake collection.
"""


class TestQueries:
    def test_list_all(self, client):
        body = client.get("/v1/decks").json()
        assert [d["name"] for d in body["items"]] == ["Default"]
        # human-readable field names, not Anki aliases
        assert "description" in body["items"][0]
        assert "browser_collapsed" in body["items"][0]

    def test_filter_by_name(self, client):
        body = client.get("/v1/decks", params={"where": "name==Default", "shape": "object"}).json()
        assert [d["id"] for d in body["items"]] == [1]

    def test_filter_by_id_index(self, client):
        body = client.get("/v1/decks", params={"where": "id==1"}).json()
        assert [d["name"] for d in body["items"]] == ["Default"]

    def test_columns_select(self, client):
        body = client.get("/v1/decks", params={"select": "id,name", "shape": "object"}).json()
        assert body["items"] == [{"id": 1, "name": "Default"}]


class TestMutations:
    def test_create(self, client):
        resp = client.post("/v1/decks", json={"name": "Japanese", "description": "JP study"})
        assert resp.status_code == 201
        deck = resp.json()["result"]
        assert deck["name"] == "Japanese"
        assert deck["description"] == "JP study"
        names = [d["name"] for d in client.get("/v1/decks").json()["items"]]
        assert "Japanese" in names

    def test_create_nested_creates_parents(self, client):
        client.post("/v1/decks", json={"name": "A::B"})
        names = [d["name"] for d in client.get("/v1/decks").json()["items"]]
        assert "A" in names and "A::B" in names

    def test_create_duplicate_is_400(self, client):
        client.post("/v1/decks", json={"name": "Japanese"})
        assert client.post("/v1/decks", json={"name": "Japanese"}).status_code == 400

    def test_create_missing_name_is_400(self, client):
        assert client.post("/v1/decks", json={"description": "x"}).status_code == 400

    def test_patch_rename_children_follow(self, client):
        deck_id = client.post("/v1/decks", json={"name": "A::B"}).json()["result"]["id"]
        parent_id = next(d["id"] for d in client.get("/v1/decks").json()["items"]
                         if d["name"] == "A")
        resp = client.patch(f"/v1/decks/{parent_id}", json={"name": "X"})
        assert resp.status_code == 200
        names = {d["id"]: d["name"] for d in client.get("/v1/decks").json()["items"]}
        assert names[parent_id] == "X"
        assert names[deck_id] == "X::B"

    def test_patch_description(self, client):
        deck_id = client.post("/v1/decks", json={"name": "Japanese"}).json()["result"]["id"]
        resp = client.patch(f"/v1/decks/{deck_id}", json={"description": "updated"})
        assert resp.json()["result"]["description"] == "updated"

    def test_patch_missing_is_404(self, client):
        assert client.patch("/v1/decks/99999", json={"name": "x"}).status_code == 404

    def test_delete(self, client):
        deck_id = client.post("/v1/decks", json={"name": "Japanese"}).json()["result"]["id"]
        assert client.delete(f"/v1/decks/{deck_id}").json()["success"] is True
        body = client.get("/v1/decks", params={"where": f"id=={deck_id}"}).json()
        assert body["items"] == []
        assert client.delete(f"/v1/decks/{deck_id}").status_code == 404

    def test_delete_default_deck_is_400(self, client):
        assert client.delete("/v1/decks/1").status_code == 400
