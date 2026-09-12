"""Page limits and projections must also bound unnecessary Anki object loading."""
from unittest.mock import patch

import pytest


def test_model_pages_load_only_returned_definitions(client, col):
    expected = sorted(int(model.id) for model in col.models.all_names_and_ids())
    cursor = None
    seen = []
    while True:
        params = {"select": "id,name,fields[].name", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        with patch.object(col.models, "get", wraps=col.models.get) as load:
            response = client.get("/v1/models", params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        ids = [row["id"] for row in page["items"]]
        assert [int(call.args[0]) for call in load.call_args_list] == ids
        assert all(row["fields"] for row in page["items"])
        seen.extend(ids)
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == expected


def test_model_name_projection_keeps_lightweight_path(client, col):
    with patch.object(col.models, "get", side_effect=AssertionError("unneeded model load")):
        response = client.get("/v1/models", params={"select": "id,name", "limit": 2})
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 2


def test_model_name_lookup_loads_only_the_match(client, col):
    expected = col.models.by_name("Basic")["id"]
    with patch.object(col.models, "get", wraps=col.models.get) as load:
        response = client.get("/v1/models", params={
            "select": "id,fields[].name", "where": 'name=="Basic"',
        })
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [{"id": expected, "fields": ["Front", "Back"]}]
    assert load.call_count == 1


def test_model_scan_does_not_enable_browser_search(client):
    response = client.get("/v1/models", params={"search": "deck:Default"})
    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]


def test_model_filter_finds_matches_after_an_entire_rejected_chunk(client, col):
    matches = []
    for number in range(55):
        model = col.models.new(f"Routing {number:02}")
        col.models.add_field(model, col.models.new_field("Front"))
        template = col.models.new_template("Card 1")
        template.update(qfmt="{{Front}}", afmt="{{Front}}")
        col.models.add_template(model, template)
        if number >= 53:
            col.models.add_field(model, col.models.new_field("Wanted"))
        col.models.add(model)
        if number >= 53:
            matches.append(int(model["id"]))
    seen = []
    cursor = None
    for _ in range(4):
        body = {"select": "id,name", "where": ['fields[].name=="Wanted"'], "limit": 1}
        if cursor:
            body["cursor"] = cursor
        response = client.post("/v1/models/query", json=body)
        assert response.status_code == 200, response.text
        page = response.json()
        seen.extend(row["id"] for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert seen == sorted(matches)


@pytest.fixture()
def note_ids(col):
    model = col.models.by_name("Basic")
    ids = []
    for front in ("target", "other"):
        note = col.new_note(model)
        note["Front"] = front
        note["Back"] = "answer"
        note.tags = ["routing"]
        col.add_note(note, col.decks.id("Default"))
        ids.append(int(note.id))
    return ids


def test_note_scalar_projection_skips_unused_names_and_field_formatting(client, col, note_ids):
    with patch.object(col.models, "all_names_and_ids", side_effect=AssertionError("unneeded model names")), \
            patch("anki.notes.Note.keys", side_effect=AssertionError("unneeded field formatting")):
        response = client.get("/v1/notes", params={"select": "id,tags"})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {"id": nid, "tags": ["routing"]} for nid in note_ids
    ]


@pytest.mark.parametrize("where,expected_count", [
    ('model_name=="Basic"', 2),
    ('fields[].value=="target"', 1),
])
def test_note_filter_still_loads_its_required_metadata(client, note_ids, where, expected_count):
    response = client.get("/v1/notes", params={"select": "id,tags", "where": where})
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["items"]] == note_ids[:expected_count]


def test_note_fields_projection_keeps_names_values_and_order(client, col, note_ids):
    with patch.object(col.models, "all_names_and_ids", side_effect=AssertionError("unneeded model names")):
        response = client.get("/v1/notes", params={"select": "id,fields", "limit": 1})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [{
        "id": note_ids[0],
        "fields": [
            {"name": "Front", "value": "target", "ord": 0},
            {"name": "Back", "value": "answer", "ord": 1},
        ],
    }]
