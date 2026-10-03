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
