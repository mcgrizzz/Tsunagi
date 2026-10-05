"""select=fields[name in [...]]: only the named fields, on notes and cards."""


def add(client, front, back):
    body = {"noteTypeName": "Basic", "deckName": "Default", "fields": {"Front": front, "Back": back}}
    return client.post("/v1/notes?include=cards", json=body).json()["created"][0]


def get(client, path, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_notes_return_only_the_named_fields(client):
    note = add(client, "犬", "<b>dog</b>")
    rows = get(client, "/v1/notes", where=f"id=={note['id']}", select='id,fields[name in ["Back"]]')
    assert rows == [{"id": note["id"], "fields": [{"name": "Back", "value": "<b>dog</b>", "index": 1}]}]
    # Plucking the value still filters by name, and the order stays the note type's.
    rows = get(client, "/v1/notes", where=f"id=={note['id']}", select='fields[name in ["Back", "Front"]].value')
    assert rows == [{"fields": ["犬", "<b>dog</b>"]}]
    assert get(client, "/v1/notes", where=f"id=={note['id']}", select='fields[name in ["Missing"]]') == [{"fields": []}]


def test_cards_filter_their_note_fields_too(client):
    card_id = add(client, "猫", "cat")["cards"][0]
    rows = get(client, "/v1/cards", where=f"id=={card_id}", select='id,fields[index in [0]].(name,value)')
    assert rows == [{"id": card_id, "fields": [{"name": "Front", "value": "猫"}]}]


def test_malformed_filter_is_a_client_error(client):
    response = client.get("/v1/notes", params={"select": "fields[name in []]"})
    assert response.status_code == 400, response.text
