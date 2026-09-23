"""Note rows are built without per-row validation; this keeps them on the schema.

The adapter names each note's values itself. If a future Anki or a schema edit
makes those rows drift from NoteInfo, this fails in CI instead of a client
receiving a different shape.
"""

from tsunagi.shared.schemas.notes import NoteField, NoteInfo


def test_rows_match_note_schema(client, col):
    saved = client.post("/v1/notes?include=cards", json=[
        {"modelName": "Basic (and reversed card)", "deckName": "Default",
         "fields": {"Front": "食べる <b>x</b>", "Back": "to eat"}, "tags": ["jp::verb", "n5"]},
        {"modelName": "Cloze", "deckName": "Default",
         "fields": {"Text": "{{c1::a}} {{c2::b}}", "Back Extra": ""}},
    ]).json()["created"]

    rows = client.get("/v1/notes").json()["items"]
    assert [row["id"] for row in rows] == [note["id"] for note in saved]
    for row, note in zip(rows, saved):
        assert list(row) == list(NoteInfo.__fields__), row
        assert NoteInfo.parse_obj(row).dict() == row
        assert type(row["guid"]) is str and type(row["model_name"]) is str
        assert all(type(row[key]) is int for key in ("id", "model_id", "mod", "usn"))
        assert all(type(tag) is str for tag in row["tags"])
        assert row["cards"] == note["cards"]
        for field in row["fields"]:
            assert list(field) == list(NoteField.__fields__), field
            assert [type(field[k]) for k in field] == [str, str, int]
    # Distinct values in each position: fields and tags map to the right names.
    assert rows[0]["fields"] == [{"name": "Front", "value": "食べる <b>x</b>", "ord": 0},
                                 {"name": "Back", "value": "to eat", "ord": 1}]
    assert rows[0]["tags"] == ["jp::verb", "n5"]
    assert rows[0]["model_name"] == "Basic (and reversed card)"
    assert rows[0]["model_id"] == col.models.by_name("Basic (and reversed card)")["id"]
    assert rows[1]["tags"] == [] and len(rows[1]["cards"]) == 2
