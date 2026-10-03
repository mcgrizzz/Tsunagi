"""A key a request body doesn't have is a 422 naming it, not quietly dropped (backlog 6.84)."""


def body_schemas(api):
    """Every schema a request body reaches through $ref, nested ones included."""
    schemas, found, stack = api["components"]["schemas"], set(), []

    def refs(node):
        if isinstance(node, dict):
            if "$ref" in node:
                yield node["$ref"].rsplit("/", 1)[-1]
            for value in node.values():
                yield from refs(value)
        elif isinstance(node, list):
            for value in node:
                yield from refs(value)

    for ops in api["paths"].values():
        for op in ops.values():
            stack += list(refs(op.get("requestBody", {})))
    while stack:
        name = stack.pop()
        if name not in found:
            found.add(name)
            stack += list(refs(schemas[name]))
    return {name: schemas[name] for name in found}


def test_every_body_schema_refuses_unknown_keys(client):
    schemas = body_schemas(client.get("/openapi.json").json())
    assert len(schemas) > 40
    assert [name for name, schema in schemas.items() if schema.get("additionalProperties") is not False] == []


def test_an_unknown_key_is_a_422_naming_it_and_nothing_is_written(client, col):
    count = col.note_count()
    r = client.post("/v1/notes", json={"modelName": "Basic", "deckName": "Default",
                                       "fields": {"Front": "a"}, "allowDuplicates": True})
    assert r.status_code == 422
    assert {"loc": ["body", "allowDuplicates"], "msg": "extra fields not permitted",
            "type": "value_error.extra"} in r.json()["errors"]
    assert col.note_count() == count


def test_fields_read_from_get_can_be_sent_back(client):
    nid = client.post("/v1/notes", json={"modelName": "Basic", "deckName": "Default",
                                         "fields": {"Front": "b"}}).json()["created"][0]["id"]
    row = client.get("/v1/notes", params={"where": f"id=={nid}", "select": "fields"}).json()["items"][0]
    assert {"name", "value", "ord"} <= set(row["fields"][0])
    assert client.patch(f"/v1/notes/{nid}", json={"fields": row["fields"]}).status_code == 200


def test_a_batch_step_takes_its_op_but_no_unknown_key(client):
    client.post("/v1/notes", json={"modelName": "Basic", "deckName": "Default", "fields": {"Front": "c"}})
    cid = client.get("/v1/cards", params={"select": "id", "shape": "scalar"}).json()["items"][0]
    step = {"op": "suspend", "card_ids": [cid]}
    assert client.post("/v1/cards:batch", json={"operations": [step]}).status_code == 200
    r = client.post("/v1/cards:batch", json={"operations": [{**step, "nope": 1}]})
    assert r.status_code == 422
    assert r.json()["errors"][0]["loc"] == ["body", "operations", 0, "nope"]


def test_create_bodies_are_documented_and_refuse_unknown_keys(client):
    # 6.99: decks, note types, fields and templates were untyped objects.
    paths = client.get("/openapi.json").json()["paths"]
    for path, schema in [("/v1/decks", "DeckCreate"), ("/v1/models", "ModelCreate"),
                         ("/v1/models/{model_id}/fields", "FieldCreate"),
                         ("/v1/models/{model_id}/templates", "TemplateCreate")]:
        body = paths[path]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert body == {"$ref": f"#/components/schemas/{schema}"} or body.get("allOf") == [
            {"$ref": f"#/components/schemas/{schema}"}], path
    r = client.post("/v1/decks", json={"name": "Typo", "descripton": "x"})
    assert r.status_code == 422 and r.json()["errors"][0]["loc"] == ["body", "descripton"]
    model = {"name": "Typed", "fields": [{"name": "Front", "sticky": True, "colour": 1}],
             "templates": [{"name": "Card 1", "qfmt": "{{Front}}", "afmt": "{{Front}}"}]}
    r = client.post("/v1/models", json=model)
    assert r.status_code == 422 and r.json()["errors"][0]["loc"] == ["body", "fields", 0, "colour"]
    del model["fields"][0]["colour"]
    created = client.post("/v1/models", json=model)
    assert created.status_code == 201
    mid = created.json()["result"]["id"]
    assert client.post(f"/v1/models/{mid}/fields", json={"name": "Back", "size": 70000}).status_code == 422
    assert client.post(f"/v1/models/{mid}/fields", json={"name": "Back", "size": 18}).status_code == 201
    assert client.post(f"/v1/models/{mid}/templates", json={"name": "Card 2", "qfmt": "{{Back}}",
                                                           "afmt": "{{Back}}", "extra": 1}).status_code == 422
    assert client.post("/v1/decks", json={"name": "Typed", "description": "ok"}).status_code == 201
