"""
Full-app spot checks for /v1/models over the fake collection - primarily the
alias-leak regression: full-row responses must use human field names
(fields/templates/sort_field), matching the where-DSL vocabulary, not Anki's
wire aliases (flds/tmpls/sortf).
"""


class TestModelsFullApp:
    def test_full_rows_use_human_field_names(self, client):
        body = client.get("/v1/models", params={"where": "name==Basic"}).json()
        (model,) = body["items"]
        assert "fields" in model and "templates" in model and "sort_field" in model
        assert "flds" not in model and "tmpls" not in model

    def test_filter_and_response_share_vocabulary(self, client):
        # The same name used in `where` appears in the response
        body = client.get("/v1/models", params={"where": "fields[].name==Front"}).json()
        assert [m["name"] for m in body["items"]] == ["Basic"]

    def test_mutation_result_uses_human_field_names(self, client):
        resp = client.post("/v1/models", json={
            "name": "Vocab",
            "fields": [{"name": "Word"}],
            "templates": [{"name": "Card 1"}],
        })
        assert resp.status_code == 201
        result = resp.json()["result"]
        assert [f["name"] for f in result["fields"]] == ["Word"]
        assert "flds" not in result
