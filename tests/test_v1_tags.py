"""
Full-app tests for /v1/tags over the fake collection.
"""
import pytest


def add(client, front, tags):
    return client.post("/v1/notes", json={
        "modelName": "Basic", "deckName": "Default",
        "fields": {"Front": front}, "tags": tags,
    }).json()["created"][0]["id"]


@pytest.fixture()
def seeded(client):
    add(client, "犬", ["vocab", "verb"])
    add(client, "猫", ["vocab", "verb::transitive"])
    return client


class TestReads:
    def test_list_is_sorted(self, seeded):
        body = seeded.get("/v1/tags").json()
        assert body["items"] == ["verb", "verb::transitive", "vocab"]
        assert "duration_ms" in body["stats"]

    def test_prefix_filter(self, seeded):
        body = seeded.get("/v1/tags", params={"prefix": "verb"}).json()
        assert body["items"] == ["verb", "verb::transitive"]

    def test_empty_collection(self, client):
        assert client.get("/v1/tags").json()["items"] == []


class TestRename:
    def test_renames_tag_and_children(self, seeded):
        # Anki's own semantics: renaming "verb" also renames "verb::transitive".
        body = seeded.patch("/v1/tags/verb", json={"name": "action"}).json()
        assert body["affected"] == 2
        assert seeded.get("/v1/tags").json()["items"] == [
            "action", "action::transitive", "vocab"]

    def test_unknown_tag_is_404(self, seeded):
        assert seeded.patch("/v1/tags/nope", json={"name": "x"}).status_code == 404

    def test_empty_new_name_is_400(self, seeded):
        assert seeded.patch("/v1/tags/verb", json={"name": "  "}).status_code == 400


class TestDelete:
    def test_removes_tag_and_children(self, seeded):
        body = seeded.delete("/v1/tags/verb").json()
        assert body["affected"] == 2
        assert seeded.get("/v1/tags").json()["items"] == ["vocab"]

    def test_leaves_other_tags_alone(self, seeded):
        seeded.delete("/v1/tags/vocab")
        assert seeded.get("/v1/tags").json()["items"] == ["verb", "verb::transitive"]

    def test_unknown_tag_is_404(self, seeded):
        assert seeded.delete("/v1/tags/nope").status_code == 404


class TestBulk:
    def test_bulk_add(self, client):
        nids = [add(client, "犬", []), add(client, "猫", [])]
        body = client.post("/v1/tags:bulk-add",
                           json={"note_ids": nids, "tags": "vocab jp"}).json()
        assert body["affected"] == 2
        assert client.get("/v1/tags").json()["items"] == ["jp", "vocab"]

    def test_bulk_remove(self, seeded):
        nids = [n["id"] for n in seeded.get("/v1/notes").json()["items"]]
        body = seeded.post("/v1/tags:bulk-remove",
                           json={"note_ids": nids, "tags": "vocab"}).json()
        assert body["affected"] == 2
        # Anki's tag registry keeps a tag after the last note drops it; only
        # clear-unused retires it. GET /v1/tags reports the registry, so the
        # tag is still listed until then.
        assert "vocab" in seeded.get("/v1/tags").json()["items"]
        notes = seeded.get("/v1/notes", params={
            "select": "id,tags", "shape": "object"}).json()["items"]
        assert all("vocab" not in n["tags"] for n in notes)
        seeded.post("/v1/tags:clear-unused")
        assert "vocab" not in seeded.get("/v1/tags").json()["items"]

    def test_camel_case_body_accepted(self, client):
        nid = add(client, "犬", [])
        assert client.post("/v1/tags:bulk-add",
                           json={"noteIds": [nid], "tags": "x"}).json()["affected"] == 1

    def test_missing_notes_are_skipped(self, client):
        nid = add(client, "犬", [])
        body = client.post("/v1/tags:bulk-add",
                           json={"note_ids": [nid, 999999], "tags": "x"}).json()
        assert body["affected"] == 1

    def test_clear_unused(self, seeded):
        # Nothing is orphaned here, so the honest answer is zero.
        assert seeded.post("/v1/tags:clear-unused").json()["affected"] == 0
