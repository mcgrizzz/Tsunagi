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


class TestClozeCreation:
    def test_create_cloze_model(self, client):
        # Regression: `type` was absent from ModelCreate, and
        # normalize_field_names round-trips through the schema, so the key was
        # dropped and every model came out standard.
        resp = client.post("/v1/models", json={
            "name": "MyCloze", "type": 1,
            "fields": [{"name": "Text"}, {"name": "Extra"}],
            "templates": [{"name": "Cloze", "qfmt": "{{cloze:Text}}", "afmt": "{{cloze:Text}}"}],
        })
        assert resp.status_code == 201
        assert resp.json()["result"]["type"] == 1

    def test_default_is_standard(self, client):
        resp = client.post("/v1/models", json={
            "name": "Plain",
            "fields": [{"name": "A"}],
            "templates": [{"name": "Card 1", "qfmt": "{{A}}", "afmt": "x"}],
        })
        assert resp.json()["result"]["type"] == 0


class TestOrdinalsAfterMutation:
    """
    Regression: Anki's new_field()/new_template() return ord=None and the
    BACKEND assigns ordinals on save, so serializing the in-memory working
    copy emitted a null ord and failed ModelInfo validation - modelFieldAdd
    reported an error even though the field had been added.
    """

    def test_add_field_returns_valid_ordinals(self, client):
        resp = client.post("/v1/models/1001/fields", json={"name": "Reading"})
        assert resp.status_code in (200, 201), resp.text
        fields = resp.json()["result"]["fields"]
        assert [f["ord"] for f in fields] == [0, 1, 2]
        assert [f["name"] for f in fields] == ["Front", "Back", "Reading"]

    def test_add_template_returns_valid_ordinals(self, client):
        resp = client.post("/v1/models/1001/templates",
                           json={"name": "Reverse", "qfmt": "{{Back}}", "afmt": "{{Front}}"})
        assert resp.status_code in (200, 201), resp.text
        assert [t["ord"] for t in resp.json()["result"]["templates"]] == [0, 1]

    def test_ordinals_renumber_after_removal(self, client):
        client.post("/v1/models/1001/fields", json={"name": "Reading"})
        resp = client.delete("/v1/models/1001/fields/Back")
        fields = resp.json()["result"]["fields"]
        # Stale ordinals from the working copy would leave a gap here.
        assert [(f["name"], f["ord"]) for f in fields] == [("Front", 0), ("Reading", 1)]

    def test_ordinals_follow_a_reorder(self, client):
        client.post("/v1/models/1001/fields", json={"name": "Reading"})
        resp = client.put("/v1/models/1001/fields:order",
                          json={"order": ["Reading", "Front", "Back"]})
        fields = resp.json()["result"]["fields"]
        assert [(f["name"], f["ord"]) for f in fields] == [
            ("Reading", 0), ("Front", 1), ("Back", 2)]
