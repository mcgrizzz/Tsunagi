"""Every error body has `detail` as a readable string; 422s list the problems in `errors`."""


def test_validation_errors_have_a_string_detail_and_a_list(client):
    response = client.post("/v1/notes", json={"modelName": "Basic", "deckName": "Default"})
    assert response.status_code == 422
    body = response.json()
    assert body["detail"].startswith("Invalid request: body")
    assert "fields" in body["detail"]
    assert any(e["loc"][-1] == "fields" for e in body["errors"])

    response = client.get("/v1/notes", params={"limit": "many"})
    assert response.status_code == 422
    assert "query.limit" in response.json()["detail"]


def test_other_errors_keep_a_string_detail(client):
    response = client.get("/v1/notes", params={"where": "id>>1"})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_openapi_documents_the_422_body(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["HTTPValidationError"]
    assert schema["properties"]["detail"]["type"] == "string"
    assert schema["properties"]["errors"]["type"] == "array"
