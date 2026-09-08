"""
Wire-shape golden tests for the AnkiConnect model actions, quoted from
canonical (git.sr.ht/~foosoft/anki-connect).

Seed: "Basic" (Front, Back / Card 1) and "Cloze" (Text, Back Extra / Cloze).
"""
from tsunagi.http.compat import actions  # noqa: F401  (registers the handlers)
from tsunagi.http.compat.errors import (
    CREATE_MODEL_NO_FIELDS,
    CREATE_MODEL_NO_TEMPLATES,
    FIELD_NOT_FOUND,
    MODEL_NAME_EXISTS,
    MODEL_NOT_FOUND,
    TEMPLATE_NOT_FOUND,
)

BASIC_QFMT = "{{Front}}"
BASIC_AFMT = "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}"


def rpc(client, action, params=None, version=6):
    body = {"action": action, "version": version}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


def fields_of(client, model="Basic"):
    return rpc(client, "modelFieldNames", {"modelName": model})["result"]


def templates_of(client, model="Basic"):
    return list(rpc(client, "modelTemplates", {"modelName": model})["result"])


class TestReads:
    def test_model_name_from_id(self, client):
        mid = rpc(client, "modelNamesAndIds")["result"]["Basic"]
        assert rpc(client, "modelNameFromId", {"modelId": mid})["result"] == "Basic"

    def test_model_name_from_unknown_id(self, client):
        resp = rpc(client, "modelNameFromId", {"modelId": 999999})
        assert resp == {"result": None, "error": MODEL_NOT_FOUND.format(999999)}

    def test_field_descriptions(self, client):
        assert rpc(client, "modelFieldDescriptions",
                   {"modelName": "Basic"})["result"] == ["", ""]

    def test_field_fonts(self, client):
        assert rpc(client, "modelFieldFonts", {"modelName": "Basic"})["result"] == {
            "Front": {"font": "Arial", "size": 20},
            "Back": {"font": "Arial", "size": 20},
        }

    def test_fields_on_templates(self, client):
        # FrontSide is a directive, and the answer side drops what the question
        # already showed.
        assert rpc(client, "modelFieldsOnTemplates",
                   {"modelName": "Basic"})["result"] == {"Card 1": [["Front"], ["Back"]]}

    def test_templates(self, client):
        assert rpc(client, "modelTemplates", {"modelName": "Basic"})["result"] == {
            "Card 1": {"Front": BASIC_QFMT, "Back": BASIC_AFMT}}

    def test_styling(self, client):
        result = rpc(client, "modelStyling", {"modelName": "Basic"})["result"]
        assert set(result) == {"css"} and "font-size" in result["css"]

    def test_unknown_model_error_string(self, client):
        for action in ("modelFieldFonts", "modelTemplates", "modelStyling",
                       "modelFieldDescriptions", "modelFieldsOnTemplates"):
            resp = rpc(client, action, {"modelName": "Nope"})
            assert resp["error"] == MODEL_NOT_FOUND.format("Nope"), action


class TestCreateModel:
    def _create(self, client, **overrides):
        params = {
            "modelName": "Custom",
            "inOrderFields": ["A", "B"],
            "cardTemplates": [{"Front": "{{A}}", "Back": "{{B}}"}],
        }
        params.update(overrides)
        return rpc(client, "createModel", params)

    def test_returns_the_raw_notetype_dict(self, client):
        model = self._create(client)["result"]
        # Anki's schema11 keys, not our curated ones.
        assert [f["name"] for f in model["flds"]] == ["A", "B"]
        assert model["name"] == "Custom" and isinstance(model["id"], int)
        assert model["tmpls"][0]["qfmt"] == "{{A}}"

    def test_template_names_default_to_card_n(self, client):
        model = self._create(client, cardTemplates=[
            {"Front": "{{A}}", "Back": "{{B}}"},
            {"Front": "{{B}}", "Back": "{{A}}"}])["result"]
        assert [t["name"] for t in model["tmpls"]] == ["Card 1", "Card 2"]

    def test_template_name_can_be_given(self, client):
        model = self._create(client, cardTemplates=[
            {"Name": "Recognition", "Front": "{{A}}", "Back": "{{B}}"}])["result"]
        assert model["tmpls"][0]["name"] == "Recognition"

    def test_is_cloze(self, client):
        assert self._create(client, isCloze=True, cardTemplates=[
            {"Front": "{{cloze:A}}", "Back": "{{cloze:A}}"}])["result"]["type"] == 1

    def test_css(self, client):
        assert self._create(client, css=".x{}")["result"]["css"] == ".x{}"

    def test_no_fields_is_an_error(self, client):
        assert self._create(client, inOrderFields=[])["error"] == CREATE_MODEL_NO_FIELDS

    def test_no_templates_is_an_error(self, client):
        assert self._create(client, cardTemplates=[])["error"] == CREATE_MODEL_NO_TEMPLATES

    def test_duplicate_name_uses_the_bare_canonical_string(self, client):
        # The native API names the model; canonical's string does not, and
        # clients match on it.
        assert self._create(client, modelName="Basic")["error"] == MODEL_NAME_EXISTS

    def test_created_model_is_listed(self, client):
        self._create(client)
        assert "Custom" in rpc(client, "modelNames")["result"]


class TestFindAndReplace:
    def _matching(self, client, needle, key="css"):
        """How many notetypes actually contain `needle` - a real collection
        ships six stock ones, so the count can't be hardcoded."""
        n = 0
        for name in rpc(client, "modelNames")["result"]:
            blob = (rpc(client, "modelStyling", {"modelName": name})["result"]["css"]
                    if key == "css"
                    else str(rpc(client, "modelTemplates", {"modelName": name})["result"]))
            n += needle in blob
        return n

    def test_counts_models_that_matched(self, client):
        expected = self._matching(client, "20px")
        assert expected                      # guard: the premise holds
        assert rpc(client, "findAndReplaceInModels", {
            "modelName": None, "findText": "20px", "replaceText": "24px"})["result"] == expected

    def test_scoped_to_one_model(self, client):
        assert rpc(client, "findAndReplaceInModels", {
            "modelName": "Basic", "findText": "20px",
            "replaceText": "24px"})["result"] == 1
        assert "24px" in rpc(client, "modelStyling",
                             {"modelName": "Basic"})["result"]["css"]

    def test_can_target_the_answer_side_only(self, client):
        # `<hr id=answer>` lives only in afmt. Rewriting {{FrontSide}} instead
        # would leave a replacement naming no field, which Anki refuses.
        expected = self._matching(client, "hr id=answer", key="templates")
        assert expected                      # guard: the premise holds
        assert rpc(client, "findAndReplaceInModels", {
            "modelName": None, "findText": "hr id=answer", "replaceText": "hr id=ANSWER",
            "css": False, "front": False})["result"] == expected

    def test_unknown_model_is_an_error(self, client):
        assert rpc(client, "findAndReplaceInModels", {
            "modelName": "Nope", "findText": "a",
            "replaceText": "b"})["error"] == MODEL_NOT_FOUND.format("Nope")


class TestUpdateModel:
    def test_update_templates(self, client):
        resp = rpc(client, "updateModelTemplates", {"model": {
            "name": "Basic",
            "templates": {"Card 1": {"Front": "{{Front}} NEW", "Back": "{{Back}} ALSO"}}}})
        assert resp == {"result": None, "error": None}
        assert rpc(client, "modelTemplates", {"modelName": "Basic"})["result"] == {
            "Card 1": {"Front": "{{Front}} NEW", "Back": "{{Back}} ALSO"}}

    def test_empty_side_is_left_alone(self, client):
        rpc(client, "updateModelTemplates", {"model": {
            "name": "Basic", "templates": {"Card 1": {"Front": "{{Front}} NEW", "Back": ""}}}})
        result = rpc(client, "modelTemplates", {"modelName": "Basic"})["result"]
        assert result["Card 1"] == {"Front": "{{Front}} NEW", "Back": BASIC_AFMT}

    def test_unknown_template_name_is_ignored(self, client):
        resp = rpc(client, "updateModelTemplates", {"model": {
            "name": "Basic", "templates": {"Nope": {"Front": "x"}}}})
        assert resp["error"] is None
        assert rpc(client, "modelTemplates",
                   {"modelName": "Basic"})["result"]["Card 1"]["Front"] == BASIC_QFMT

    def test_update_styling(self, client):
        rpc(client, "updateModelStyling", {"model": {"name": "Basic", "css": ".new{}"}})
        assert rpc(client, "modelStyling",
                   {"modelName": "Basic"})["result"] == {"css": ".new{}"}


class TestTemplateEdits:
    def test_rename(self, client):
        rpc(client, "modelTemplateRename", {
            "modelName": "Basic", "oldTemplateName": "Card 1",
            "newTemplateName": "Recognition"})
        assert templates_of(client) == ["Recognition"]

    def test_rename_unknown_template(self, client):
        resp = rpc(client, "modelTemplateRename", {
            "modelName": "Basic", "oldTemplateName": "Nope", "newTemplateName": "x"})
        assert resp["error"] == TEMPLATE_NOT_FOUND.format("Basic", "Nope")

    def test_add_new_template(self, client):
        rpc(client, "modelTemplateAdd", {"modelName": "Basic", "template": {
            "Name": "Reverse", "Front": "{{Back}}", "Back": "{{Front}}"}})
        assert templates_of(client) == ["Card 1", "Reverse"]

    def test_add_existing_template_persists_the_update(self, client):
        # DEVIATION: canonical returns without saving here, silently discarding
        # the update.
        rpc(client, "modelTemplateAdd", {"modelName": "Basic", "template": {
            "Name": "Card 1", "Front": "{{Front}} CHANGED", "Back": "{{Back}} ALSO"}})
        assert rpc(client, "modelTemplates", {"modelName": "Basic"})["result"] == {
            "Card 1": {"Front": "{{Front}} CHANGED", "Back": "{{Back}} ALSO"}}

    def test_reposition(self, client):
        rpc(client, "modelTemplateAdd", {"modelName": "Basic", "template": {
            "Name": "Reverse", "Front": "{{Back}}", "Back": "{{Front}}"}})
        rpc(client, "modelTemplateReposition", {
            "modelName": "Basic", "templateName": "Reverse", "index": 0})
        assert templates_of(client) == ["Reverse", "Card 1"]

    def test_remove(self, client):
        rpc(client, "modelTemplateAdd", {"modelName": "Basic", "template": {
            "Name": "Reverse", "Front": "a", "Back": "b"}})
        rpc(client, "modelTemplateRemove", {"modelName": "Basic",
                                            "templateName": "Reverse"})
        assert templates_of(client) == ["Card 1"]

    def test_remove_unknown_template(self, client):
        resp = rpc(client, "modelTemplateRemove", {"modelName": "Basic",
                                                   "templateName": "Nope"})
        assert resp["error"] == TEMPLATE_NOT_FOUND.format("Basic", "Nope")


class TestFieldEdits:
    def test_rename(self, client):
        rpc(client, "modelFieldRename", {
            "modelName": "Basic", "oldFieldName": "Front", "newFieldName": "Word"})
        assert fields_of(client) == ["Word", "Back"]

    def test_rename_unknown_field(self, client):
        resp = rpc(client, "modelFieldRename", {
            "modelName": "Basic", "oldFieldName": "Nope", "newFieldName": "x"})
        assert resp["error"] == FIELD_NOT_FOUND.format("Basic", "Nope")

    def test_add(self, client):
        rpc(client, "modelFieldAdd", {"modelName": "Basic", "fieldName": "Reading"})
        assert fields_of(client) == ["Front", "Back", "Reading"]

    def test_add_with_index(self, client):
        rpc(client, "modelFieldAdd", {"modelName": "Basic",
                                      "fieldName": "Reading", "index": 1})
        assert fields_of(client) == ["Front", "Reading", "Back"]

    def test_add_existing_field_still_repositions(self, client):
        # Canonical adds only when absent, but repositions either way.
        rpc(client, "modelFieldAdd", {"modelName": "Basic",
                                      "fieldName": "Back", "index": 0})
        assert fields_of(client) == ["Back", "Front"]

    def test_add_existing_field_without_index_is_a_no_op(self, client):
        rpc(client, "modelFieldAdd", {"modelName": "Basic", "fieldName": "Back"})
        assert fields_of(client) == ["Front", "Back"]

    def test_reposition(self, client):
        rpc(client, "modelFieldReposition", {
            "modelName": "Basic", "fieldName": "Back", "index": 0})
        assert fields_of(client) == ["Back", "Front"]

    def test_remove(self, client):
        rpc(client, "modelFieldAdd", {"modelName": "Basic", "fieldName": "Reading"})
        rpc(client, "modelFieldRemove", {"modelName": "Basic", "fieldName": "Reading"})
        assert fields_of(client) == ["Front", "Back"]

    def test_remove_unknown_field(self, client):
        resp = rpc(client, "modelFieldRemove", {"modelName": "Basic",
                                                "fieldName": "Nope"})
        assert resp["error"] == FIELD_NOT_FOUND.format("Basic", "Nope")


class TestFieldProperties:
    def test_set_font(self, client):
        rpc(client, "modelFieldSetFont", {
            "modelName": "Basic", "fieldName": "Front", "font": "Noto Sans JP"})
        fonts = rpc(client, "modelFieldFonts", {"modelName": "Basic"})["result"]
        assert fonts["Front"]["font"] == "Noto Sans JP"

    def test_set_font_rejects_non_strings(self, client):
        resp = rpc(client, "modelFieldSetFont", {
            "modelName": "Basic", "fieldName": "Front", "font": 12})
        assert resp["error"] == "font should be a string: 12"

    def test_set_font_size(self, client):
        rpc(client, "modelFieldSetFontSize", {
            "modelName": "Basic", "fieldName": "Front", "fontSize": 44})
        fonts = rpc(client, "modelFieldFonts", {"modelName": "Basic"})["result"]
        assert fonts["Front"]["size"] == 44

    def test_set_font_size_rejects_non_integers(self, client):
        resp = rpc(client, "modelFieldSetFontSize", {
            "modelName": "Basic", "fieldName": "Front", "fontSize": "44"})
        assert resp["error"] == "fontSize should be an integer: 44"

    def test_set_description_returns_true(self, client):
        resp = rpc(client, "modelFieldSetDescription", {
            "modelName": "Basic", "fieldName": "Front", "description": "the word"})
        assert resp["result"] is True
        assert rpc(client, "modelFieldDescriptions",
                   {"modelName": "Basic"})["result"] == ["the word", ""]

    def test_set_description_rejects_non_strings(self, client):
        resp = rpc(client, "modelFieldSetDescription", {
            "modelName": "Basic", "fieldName": "Front", "description": 5})
        assert resp["error"] == "description should be a string: 5"

    def test_unknown_field_error_string(self, client):
        resp = rpc(client, "modelFieldSetFont", {
            "modelName": "Basic", "fieldName": "Nope", "font": "Arial"})
        assert resp["error"] == FIELD_NOT_FOUND.format("Basic", "Nope")
