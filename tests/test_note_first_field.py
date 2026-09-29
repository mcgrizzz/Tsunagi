"""`first_field`: notes for given words, from Anki's first-field index."""
import json

from tsunagi.http.v1.notes import caps
from tsunagi.shared.planning import make_plan


def add(client, front, model="Basic", deck="Default"):
    body = {"modelName": model, "deckName": deck, "allowDuplicate": True,
            "fields": {"Front": front, "Back": "meaning"}}
    return client.post("/v1/notes", json=body).json()["created"][0]["id"]


def lookup(client, *words, **params):
    where = f"first_field in {json.dumps(list(words), ensure_ascii=False)}"
    response = client.get("/v1/notes", params={"where": where, "select": "id,first_field", **params})
    assert response.status_code == 200, response.text
    return sorted((row["id"], row["first_field"]) for row in response.json()["items"])


def test_rows_carry_the_first_fields_value(client):
    nid = add(client, "犬")
    row = client.get("/v1/notes", params={"where": f"id=={nid}"}).json()["items"][0]
    assert row["first_field"] == row["fields"][0]["value"] == "犬"


def test_lookup_finds_every_note_type_and_only_exact_values(client):
    basic = add(client, "よし")
    reversed_ = add(client, "よし", model="Basic (and reversed card)")
    other = add(client, "どれだけ")
    bold = add(client, "<b>よし</b>")
    add(client, "よしよし")
    assert lookup(client, "よし", "どれだけ") == sorted(
        [(basic, "よし"), (reversed_, "よし"), (other, "どれだけ")])
    # The index ignores HTML; the exact comparison still applies.
    assert lookup(client, "<b>よし</b>") == [(bold, "<b>よし</b>")]
    assert lookup(client, "missing") == []


def test_lookup_uses_the_index_and_combines_with_other_filters(client):
    assert make_plan("id", ['first_field in ["よし"]'], caps).mode == "index"
    add(client, "よし")
    reversed_ = add(client, "よし", model="Basic (and reversed card)")
    response = client.get("/v1/notes", params=[
        ("where", 'first_field=="よし"'), ("where", 'model_name=="Basic (and reversed card)"'),
        ("select", "id")])
    assert response.json()["items"] == [reversed_]


def test_non_string_values_match_nothing(client):
    add(client, "1")
    response = client.get("/v1/notes", params={"where": "first_field==1", "select": "id"})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
