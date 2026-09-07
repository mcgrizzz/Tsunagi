"""Model/scheduler regressions that do not require an upstream checkout."""

from tsunagi.adapters.anki.models import patch_field
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
