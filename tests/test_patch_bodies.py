"""PATCH bodies are typed (backlog 6.57): OpenAPI shows each schema, and a bad body is the usual 422."""
import pytest


@pytest.fixture()
def nid(client, col):
    return client.post("/v1/notes", json={"modelName": "Basic", "deckName": "Default",
                                          "fields": {"Front": "a", "Back": ""}}).json()["created"][0]["id"]


def test_openapi_names_each_patch_schema(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path, schema in [("/v1/notes/{id}", "NotePatch"), ("/v1/decks/{id}", "DeckPatch"),
                         ("/v1/models/{id}", "ModelPatch"),
                         ("/v1/models/{model_id}/fields/{field_id}", "FieldPatch"),
                         ("/v1/models/{model_id}/templates/{template_id}", "TemplatePatch")]:
        body = paths[path]["patch"]["requestBody"]["content"]["application/json"]["schema"]
        assert body["allOf"] == [{"$ref": f"#/components/schemas/{schema}"}], path


@pytest.mark.parametrize("body", [{"fields": 5}, {"tags": "x"}, "text"])
def test_a_bad_note_patch_is_a_422_before_any_write(client, col, nid, body):
    mod = col.get_note(nid).mod
    r = client.patch(f"/v1/notes/{nid}", json=body)
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], str) and r.json()["errors"]
    assert col.get_note(nid).mod == mod


def test_snake_and_camel_keys_both_reach_the_note(client, col, nid):
    assert client.patch(f"/v1/notes/{nid}", json={"addTags": ["a"]}).status_code == 200
    assert client.patch(f"/v1/notes/{nid}", json={"add_tags": ["b"], "fields": {"Back": "x"}}).status_code == 200
    note = col.get_note(nid)
    assert sorted(note.tags) == ["a", "b"] and note["Back"] == "x"


def test_an_unknown_key_is_a_422_before_any_write(client, col, nid):
    mod = col.get_note(nid).mod
    r = client.patch(f"/v1/notes/{nid}", json={"nope": 1})
    assert r.status_code == 422 and r.json()["errors"][0]["loc"] == ["body", "nope"]
    assert col.get_note(nid).mod == mod


def test_an_explicit_null_still_reaches_the_adapter(client, col):
    did = col.decks.id("Retention")
    assert client.patch(f"/v1/decks/{did}", json={"desired_retention": 0.8}).status_code == 200
    assert client.patch(f"/v1/decks/{did}", json={"desired_retention": None}).status_code == 200
    rows = client.get("/v1/decks", params={"where": f"id=={did}", "select": "desired_retention"}).json()["items"]
    assert rows == [{"desired_retention": None}]
