"""Model/scheduler regressions that do not require an upstream checkout."""

import pytest

from tsunagi.adapters.anki.models import find_and_replace_in_models, patch_field
from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc


def rpc(action, **params):
    return handle_ankiconnect_rpc({"action": action, "version": 6, "params": params})


def test_native_field_rename_preserves_rendering_and_other_updates(col, client):
    model = col.models.by_name("Basic")
    note = col.new_note(model)
    note["Front"], note["Back"] = "question text", "answer text"
    col.add_note(note, col.decks.id("Default"))
    patch_field(model["id"], "Front", {"name": "Question", "font": "Arial"})
    col.models._clear_cache()
    saved = col.models.get(model["id"])
    assert saved["flds"][0]["name"] == "Question"
    assert saved["flds"][0]["font"] == "Arial"
    assert "{{Question}}" in saved["tmpls"][0]["qfmt"]
    assert "{{Front}}" not in saved["tmpls"][0]["qfmt"]
    assert "question text" in col.get_card(note.card_ids()[0]).question()


def test_existing_template_add_changes_cache_without_saving(col, client):
    original = col.models.by_name("Basic")["tmpls"][0]["qfmt"]
    response = rpc("modelTemplateAdd", modelName="Basic", template={
        "Name": "Card 1", "Front": "{{Back}}", "Back": "{{Front}}",
    })
    assert response == {"result": None, "error": None}
    assert col.models.by_name("Basic")["tmpls"][0]["qfmt"] == "{{Back}}"
    col.models._clear_cache()
    assert col.models.by_name("Basic")["tmpls"][0]["qfmt"] == original


def test_empty_template_update_still_marks_model_for_sync(col, client):
    response = rpc("updateModelTemplates", model={"name": "Basic", "templates": {}})
    assert response == {"result": None, "error": None}
    col.models._clear_cache()
    assert col.models.by_name("Basic")["usn"] == -1


def test_short_ease_array_keeps_prefix_writes_and_skips_missing_cards(col, client):
    ids = []
    for front in ["first", "second"]:
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = front
        col.add_note(note, col.decks.id("Default"))
        ids.append(note.card_ids()[0])
    response = rpc("setEaseFactors", cards=ids, easeFactors=[2100])
    assert response == {"result": None, "error": "list index out of range"}
    assert col.get_card(ids[0]).factor == 2100
    assert col.get_card(ids[1]).factor == 0
    response = rpc("setEaseFactors", cards=[ids[0], 9999999999999], easeFactors=[2200])
    assert response == {"result": [True, False], "error": None}
    assert col.get_card(ids[0]).factor == 2200


def test_due_date_error_uses_anki_message(client):
    assert rpc("setDueDate", cards=[], days="invalid") == {
        "result": None, "error": "invalid",
    }


@pytest.mark.parametrize("missing", ["Front", "Back"])
def test_create_model_requires_both_template_sides(col, client, missing):
    template = {"Front": "{{Front}}", "Back": "{{Back}}"}
    del template[missing]
    response = rpc("createModel", modelName="Missing side", inOrderFields=["Front", "Back"],
                   cardTemplates=[template])
    assert response == {"result": None, "error": repr(missing)}
    assert col.models.by_name("Missing side") is None


def test_create_model_exposes_anki_template_validation_error(col, client):
    response = rpc("createModel", modelName="Broken template", inOrderFields=["Front"],
                   cardTemplates=[{"Front": "{{Missing}}", "Back": "{{Front}}"}])
    assert response["result"] is None
    assert "Card template" in response["error"]
    assert "Broken template" in response["error"]
    assert col.models.by_name("Broken template") is None


@pytest.mark.parametrize("model_name", ["Basic", None])
def test_replacement_saves_unmatched_only_when_requested(col, client, model_name):
    before = {model["name"]: model["usn"] for model in col.models.all()}
    assert find_and_replace_in_models("not present", "replacement", model_name) == 0
    col.models._clear_cache()
    assert {model["name"]: model["usn"] for model in col.models.all()} == before
    assert rpc("findAndReplaceInModels", modelName=model_name,
               findText="not present", replaceText="replacement") == {"result": 0, "error": None}
    col.models._clear_cache()
    for model in col.models.all():
        expected = -1 if model_name is None or model["name"] == model_name else before[model["name"]]
        assert model["usn"] == expected


@pytest.mark.parametrize("malformed,error", [
    ({"ease": 4}, "'cardId'"),
    ({"cardId": 9999999999999}, "'ease'"),
])
def test_answer_prefix_survives_malformed_entry_and_can_be_undone(col, client, malformed, error):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "answer prefix"
    col.add_note(note, col.decks.id("Default"))
    cid = note.card_ids()[0]
    response = rpc("answerCards", answers=[{"cardId": cid, "ease": 4}, malformed])
    assert response == {"result": None, "error": error}
    assert col.get_card(cid).reps == 1
    assert col.db.scalar("select count(*) from revlog where cid = ?", cid) == 1
    col.undo()
    assert col.get_card(cid).reps == 0
    assert col.db.scalar("select count(*) from revlog where cid = ?", cid) == 0


def test_invalid_ease_takes_precedence_over_later_missing_key(col, client):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "invalid ease before malformed entry"
    col.add_note(note, col.decks.id("Default"))
    cid = note.card_ids()[0]
    response = rpc("answerCards", answers=[{"cardId": cid, "ease": 0}, {}])
    assert response == {"result": None, "error": "invalid ease"}
    assert col.get_card(cid).reps == 0
