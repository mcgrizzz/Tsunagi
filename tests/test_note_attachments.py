"""Files sent with a note on POST /v1/notes (audio, video, picture)."""
import base64

import tsunagi.http.v1.media as media_routes


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def note(front, **attachments):
    return {"modelName": "Basic", "deckName": "Default",
            "fields": {"Front": front, "Back": "meaning"}, **attachments}


def fields_of(col, note_id):
    return dict(col.get_note(note_id).items())


def test_one_request_stores_the_files_and_references_them(client, col, monkeypatch):
    fetched = []
    def fetch(url):
        fetched.append(url)
        return b"mp3 bytes"
    monkeypatch.setattr(media_routes, "_fetch_url", fetch)
    body = note("犬",
                audio={"url": "https://example.com/inu.mp3", "filename": "inu.mp3", "fields": ["Front"]},
                picture=[{"data": b64(b"png bytes"), "filename": "inu.png", "fields": ["Back"]}])
    response = client.post("/v1/notes", json=body)
    assert response.status_code == 200, response.text
    nid = response.json()["created"][0]["id"]
    assert fetched == ["https://example.com/inu.mp3"]
    assert fields_of(col, nid) == {"Front": "犬[sound:inu.mp3]", "Back": 'meaning<img src="inu.png">'}
    assert col.media.have("inu.mp3") and col.media.have("inu.png")
    # One undo step removes the note (media files are not part of Anki's undo).
    col.undo()
    assert col.note_count() == 0


def test_a_rejected_note_stores_none_of_its_files(client, col):
    client.post("/v1/notes", json=note("犬"))
    batch = [
        note("猫", picture={"data": b64(b"cat"), "filename": "neko.png", "fields": ["Back"]}),
        note("犬", picture={"data": b64(b"dog"), "filename": "dup.png", "fields": ["Back"]}),
        note("鳥", audio={"data": "not base64!", "filename": "tori.mp3", "fields": ["Back"]}),
        note("魚", audio={"data": b64(b"fish"), "filename": "sakana.mp3", "fields": ["Missing"]}),
        note("牛", video={"data": b64(b"cow"), "filename": "ushi.mp4"}),
    ]
    answer = client.post("/v1/notes", json=batch).json()
    assert [c["index"] for c in answer["created"]] == [0, 4]
    assert {f["index"]: f["code"] for f in answer["failed"]} == {
        1: "duplicate", 2: "invalid_attachment", 3: "invalid_note"}
    assert col.media.have("neko.png") and col.media.have("ushi.mp4")   # no fields: stored only
    assert not any(col.media.have(n) for n in ("dup.png", "tori.mp3", "sakana.mp3"))


def test_a_renamed_file_keeps_its_reference(client, col):
    col.media.write_data("same.png", b"already here")
    nid = client.post("/v1/notes", json=note(
        "馬", picture={"data": b64(b"different"), "filename": "same.png", "fields": ["Back"]})).json()["created"][0]["id"]
    stored = fields_of(col, nid)["Back"].split('"')[1]
    assert stored != "same.png" and col.media.have(stored)
    assert fields_of(col, nid)["Back"] == f'meaning<img src="{stored}">'


def test_upsert_refuses_attachments(client, col):
    answer = client.post("/v1/notes:upsert", json=note(
        "羊", picture={"data": b64(b"sheep"), "filename": "hitsuji.png", "fields": ["Back"]})).json()
    assert answer["failed"][0]["code"] == "invalid_note" and "POST /v1/media" in answer["failed"][0]["message"]
    assert col.note_count() == 0 and not col.media.have("hitsuji.png")
