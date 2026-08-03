"""
Full-app spot checks for /v1/models - primarily the alias-leak regression:
full-row responses must use human field names (fields/templates/sort_field),
matching the where-DSL vocabulary, not Anki's wire aliases (flds/tmpls/sortf).

A real collection ships six stock notetypes, four of which have a `Front`
field. Assertions here name what they mean instead of relying on a sparse
collection, and resolve notetype ids from the API - Anki assigns epoch-ms ids.
"""
import pytest


@pytest.fixture()
def basic_id(client):
    return client.get("/v1/models", params={
        "where": "name==Basic", "select": "id", "shape": "scalar"}).json()["items"][0]


def _models_where(client, field, needle):
    """Names of models whose `field` contains `needle`, straight from the API."""
    rows = client.get("/v1/models", params={
        "select": f"name,{field}", "shape": "object"}).json()["items"]
    return [r["name"] for r in rows if needle in str(r[field])]


class TestModelsFullApp:
    def test_full_rows_use_human_field_names(self, client):
        body = client.get("/v1/models", params={"where": "name==Basic"}).json()
        (model,) = body["items"]
        assert "fields" in model and "templates" in model and "sort_field" in model
        assert "flds" not in model and "tmpls" not in model

    def test_filter_and_response_share_vocabulary(self, client):
        # The same name used in `where` appears in the response. Several stock
        # notetypes have a Front field; Cloze (Text/Back Extra) has none, so
        # this still proves the filter discriminates.
        body = client.get("/v1/models", params={"where": "fields[].name==Front"}).json()
        names = [m["name"] for m in body["items"]]
        assert "Basic" in names and "Cloze" not in names
        for model in body["items"]:
            assert "Front" in [f["name"] for f in model["fields"]]

    def test_mutation_result_uses_human_field_names(self, client):
        resp = client.post("/v1/models", json={
            "name": "Vocab",
            "fields": [{"name": "Word"}],
            "templates": [{"name": "Card 1", "qfmt": "{{Word}}", "afmt": "{{Word}}"}],
        })
        assert resp.status_code == 201
        result = resp.json()["result"]
        assert [f["name"] for f in result["fields"]] == ["Word"]
        assert "flds" not in result


class TestFindReplace:
    def _css(self, client, mid):
        return client.get("/v1/models", params={
            "where": f"id=={mid}", "select": "css", "shape": "scalar"}).json()["items"][0]

    def test_replaces_in_css_and_templates(self, client, basic_id):
        expected = _models_where(client, "css", "20px")
        assert "Basic" in expected                 # guard: the premise holds
        body = client.post("/v1/models:find-replace",
                           json={"find": "20px", "replace": "24px"}).json()
        assert body["affected"] == len(expected)
        assert "24px" in self._css(client, basic_id)

    def test_scoped_to_one_model(self, client, basic_id):
        cloze_id = client.get("/v1/models", params={
            "where": "name==Cloze", "select": "id", "shape": "scalar"}).json()["items"][0]
        body = client.post("/v1/models:find-replace", json={
            "find": "20px", "replace": "24px", "model_name": "Basic"}).json()
        assert body["affected"] == 1
        assert "24px" in self._css(client, basic_id)
        assert "20px" in self._css(client, cloze_id)   # every other model untouched

    def test_sides_can_be_excluded(self, client):
        # `<hr id=answer>` only ever appears in afmt, so restricting to the
        # answer side must still reach every model that uses it. (Rewriting a
        # field replacement here instead would leave the notetype invalid and
        # Anki would - correctly - refuse the save.)
        expected = _models_where(client, "templates", "hr id=answer")
        assert expected                            # guard: the premise holds
        body = client.post("/v1/models:find-replace", json={
            "find": "hr id=answer", "replace": "hr id=ANSWER",
            "css": False, "front": False, "back": True}).json()
        assert body["affected"] == len(expected)

    def test_no_match_affects_nothing(self, client):
        body = client.post("/v1/models:find-replace",
                           json={"find": "nowhere-at-all", "replace": "x"}).json()
        assert body["affected"] == 0

    def test_unknown_model_is_404(self, client):
        resp = client.post("/v1/models:find-replace",
                           json={"find": "a", "replace": "b", "model_name": "Nope"})
        assert resp.status_code == 404


class TestInvalidTemplates:
    """
    Regression: Anki rejects a notetype whose template has no field
    replacement, raising CardTypeError. Nothing mapped it, so a bad request
    came back as a 500 with a generic "Create failed" - discarding the message
    Anki wrote for the user. The fake never validated templates at all.
    """

    def test_template_without_a_field_replacement_is_400(self, client):
        resp = client.post("/v1/models", json={
            "name": "Broken", "fields": [{"name": "Word"}],
            "templates": [{"name": "Card 1"}],
        })
        assert resp.status_code == 400
        assert "field replacement" in resp.json()["detail"]

    def test_template_naming_a_missing_field_is_400(self, client):
        resp = client.post("/v1/models", json={
            "name": "Broken2", "fields": [{"name": "Word"}],
            "templates": [{"name": "Card 1", "qfmt": "{{Nope}}", "afmt": "{{Nope}}"}],
        })
        assert resp.status_code == 400

    def test_detail_carries_no_directional_isolates(self, client):
        # Anki wraps interpolated names in U+2068/U+2069 for RTL rendering;
        # they are invisible junk in a JSON response.
        detail = client.post("/v1/models", json={
            "name": "Broken3", "fields": [{"name": "Word"}],
            "templates": [{"name": "Card 1"}],
        }).json()["detail"]
        assert not set(detail) & set("⁦⁧⁨⁩")


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

    def test_add_field_returns_valid_ordinals(self, client, basic_id):
        resp = client.post(f"/v1/models/{basic_id}/fields", json={"name": "Reading"})
        assert resp.status_code in (200, 201), resp.text
        fields = resp.json()["result"]["fields"]
        assert [f["ord"] for f in fields] == [0, 1, 2]
        assert [f["name"] for f in fields] == ["Front", "Back", "Reading"]

    def test_add_template_returns_valid_ordinals(self, client, basic_id):
        resp = client.post(f"/v1/models/{basic_id}/templates",
                           json={"name": "Reverse", "qfmt": "{{Back}}", "afmt": "{{Front}}"})
        assert resp.status_code in (200, 201), resp.text
        assert [t["ord"] for t in resp.json()["result"]["templates"]] == [0, 1]

    def test_ordinals_renumber_after_removal(self, client, basic_id):
        client.post(f"/v1/models/{basic_id}/fields", json={"name": "Reading"})
        resp = client.delete(f"/v1/models/{basic_id}/fields/Back")
        fields = resp.json()["result"]["fields"]
        # Stale ordinals from the working copy would leave a gap here.
        assert [(f["name"], f["ord"]) for f in fields] == [("Front", 0), ("Reading", 1)]

    def test_ordinals_follow_a_reorder(self, client, basic_id):
        client.post(f"/v1/models/{basic_id}/fields", json={"name": "Reading"})
        resp = client.put(f"/v1/models/{basic_id}/fields:order",
                          json={"order": ["Reading", "Front", "Back"]})
        fields = resp.json()["result"]["fields"]
        assert [(f["name"], f["ord"]) for f in fields] == [
            ("Reading", 0), ("Front", 1), ("Back", 2)]
