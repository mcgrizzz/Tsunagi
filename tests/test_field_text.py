"""fields[].text: a field without HTML, built only when select or where names it."""


def add(client, front, back):
    body = {"noteTypeName": "Basic", "deckName": "Default", "fields": {"Front": front, "Back": back},
            "allowDuplicate": True}
    return client.post("/v1/notes?include=cards", json=body).json()["created"][0]


def get(client, path, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_notes_select_text_with_media_filenames_kept(client):
    note = add(client, "<b>犬</b>[sound:inu.mp3]", '<div>dog</div><img src="dog.jpg">')
    rows = get(client, "/v1/notes", where=f"id=={note['id']}", select="fields[].(name,text)")
    assert rows == [{"fields": [{"name": "Front", "text": "犬inu.mp3"}, {"name": "Back", "text": "dog dog.jpg"}]}]
    rows = get(client, "/v1/notes", where=f"id=={note['id']}", select='fields[name in ["Back"]].text')
    assert rows == [{"fields": ["dog dog.jpg"]}]


def test_text_is_absent_unless_named(client):
    note = add(client, "<b>犬</b>", "dog")
    for params in ({}, {"select": "fields"}, {"select": "fields[]"}):
        [row] = get(client, "/v1/notes", where=f"id=={note['id']}", **params)
        assert all("text" not in field for field in row["fields"]), params
    for where in (f"id=={note['cards'][0]}", f"note_id=={note['id']}"):  # search and note-id reads
        [row] = get(client, "/v1/cards", where=where)
        assert all("text" not in field for field in row["fields"]), where
    patched = client.patch(f"/v1/notes/{note['id']}", json={"fields": {"Back": "dogs"}}).json()["result"]
    assert all("text" not in field for field in patched["fields"])


def test_where_on_text(client):
    note = add(client, "<i>猫</i>", "cat")
    add(client, "猫", "<b>cat</b>s")
    rows = get(client, "/v1/notes", where=['fields[].text=="猫"', 'fields[].value=="cat"'], select="id")
    assert rows == [{"id": note["id"]}]
    # No select: the whole row, with its text.
    [row] = get(client, "/v1/notes", where=['fields[].text=="猫"', 'fields[].value=="cat"'])
    assert row["cards"] == note["cards"] and row["note_type_name"] == "Basic"
    assert [field["text"] for field in row["fields"]] == ["猫", "cat"]


def test_cards_select_and_filter_on_text(client):
    card_id = add(client, "<b>鳥</b>", "bird")["cards"][0]
    add(client, "鳥", "birds")
    # The rendered question is built only for the rows that pass the text filter.
    rows = get(client, "/v1/cards", where='fields[].text=="鳥"', select="id,question,fields[].text")
    assert [row["id"] for row in rows if row["fields"] == ["鳥", "bird"]] == [card_id]
    assert all("鳥" in row["question"] for row in rows) and len(rows) == 2
