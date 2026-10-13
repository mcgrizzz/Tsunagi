"""Every error body has `detail` as a readable string; 422s list the problems in `errors`."""


def test_validation_errors_have_a_string_detail_and_a_list(client):
    response = client.post("/v1/notes", json={"noteTypeName": "Basic", "deckName": "Default"})
    assert response.status_code == 422
    body = response.json()
    assert body["detail"].startswith("Invalid request: body")
    assert "fields" in body["detail"]
    assert any(e["loc"][-1] == "fields" for e in body["errors"])

    response = client.get("/v1/notes", params={"limit": "many"})
    assert response.status_code == 422
    assert "query.limit" in response.json()["detail"]


def test_a_one_or_array_body_gets_the_errors_for_the_shape_it_sent(client):
    # 6.89: not "body: value is not a valid list" next to an object's errors.
    one = client.post("/v1/notes", json={"noteTypeName": "Basic", "deckName": "Default"}).json()
    assert [e["loc"] for e in one["errors"]] == [["body", "fields"]]
    assert one["detail"] == "Invalid request: body.fields: field required"
    many = client.post("/v1/notes", json=[{"noteTypeName": "Basic", "deckName": "Default"}]).json()
    assert [e["loc"] for e in many["errors"]] == [["body", 0, "fields"]]
    wrong = client.post("/v1/notes", json="text").json()
    assert len(wrong["errors"]) > 1  # neither shape: both say why


def test_other_errors_keep_a_string_detail(client):
    response = client.get("/v1/notes", params={"where": "id>>1"})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_openapi_documents_the_422_body(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["HTTPValidationError"]
    assert schema["properties"]["detail"]["type"] == "string"
    assert schema["properties"]["errors"]["type"] == "array"
