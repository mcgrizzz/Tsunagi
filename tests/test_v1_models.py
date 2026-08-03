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


class TestFindReplace:
    def _css(self, client, mid):
        return client.get("/v1/models", params={
            "where": f"id=={mid}", "select": "css", "shape": "scalar"}).json()["items"][0]

    def test_replaces_in_css_and_templates(self, client):
        body = client.post("/v1/models:find-replace",
                           json={"find": "20px", "replace": "24px"}).json()
        assert body["affected"] == 2          # both seeded models carry the css
        assert "24px" in self._css(client, 1001)

    def test_scoped_to_one_model(self, client):
        body = client.post("/v1/models:find-replace", json={
            "find": "20px", "replace": "24px", "model_name": "Basic"}).json()
        assert body["affected"] == 1
        assert "24px" in self._css(client, 1001)
        assert "20px" in self._css(client, 1002)   # Cloze untouched

    def test_sides_can_be_excluded(self, client):
        body = client.post("/v1/models:find-replace", json={
            "find": "FrontSide", "replace": "GONE",
            "css": False, "front": False, "back": True}).json()
        assert body["affected"] == 2          # FrontSide only appears in afmt

    def test_no_match_affects_nothing(self, client):
        body = client.post("/v1/models:find-replace",
                           json={"find": "nowhere-at-all", "replace": "x"}).json()
        assert body["affected"] == 0

    def test_unknown_model_is_404(self, client):
        resp = client.post("/v1/models:find-replace",
                           json={"find": "a", "replace": "b", "model_name": "Nope"})
        assert resp.status_code == 404
