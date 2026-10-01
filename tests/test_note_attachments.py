"""Files sent with a note on POST /v1/notes and PATCH /v1/notes/{id} (audio, video, picture)."""
import base64

import pytest

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


def test_created_notes_report_their_files_as_stored(client, col):
    col.media.write_data("inu.png", b"other bytes")   # Anki renames a new inu.png
    body = [note("犬", audio={"data": b64(b"mp3 bytes"), "filename": "inu.mp3", "fields": ["Front"]},
                 picture={"data": b64(b"png bytes"), "filename": "inu.png", "fields": []}),
            note("猫")]
    body[0]["fields"]["Back"] = '<img src="inu.png">'   # a reference the attachment doesn't list
    created = client.post("/v1/notes", json=body).json()["created"]
    audio, picture = created[0]["files"]
    assert audio == {"filename": "inu.mp3", "requested_filename": "inu.mp3", "renamed": False, "size": 9}
    assert picture["renamed"] and picture["requested_filename"] == "inu.png"
    assert picture["filename"] != "inu.png" and col.media.have(picture["filename"])
    # Only listed fields follow a rename; the client fixes the others with the reported name.
    assert fields_of(col, created[0]["id"])["Back"] == '<img src="inu.png">'
    assert "files" not in created[1]


def test_a_failed_attachment_names_the_file(client, col):
    body = note("鳥", audio={"data": b64(b"ok"), "filename": "tori.mp3"},
                picture=[{"data": b64(b"ok"), "filename": "ok.png"},
                         {"data": "not base64!", "filename": "bad.png", "fields": ["Back"]}])
    (failure,) = client.post("/v1/notes", json=body).json()["failed"]
    assert failure["code"] == "invalid_attachment"
    assert failure["attachment"] == {"kind": "picture", "position": 1, "filename": "bad.png"}
    assert "base64" in failure["message"]
    assert not any(col.media.have(n) for n in ("tori.mp3", "ok.png", "bad.png"))


def test_other_failures_have_no_attachment(client, col):
    client.post("/v1/notes", json=note("犬"))
    (failure,) = client.post("/v1/notes", json=note("犬")).json()["failed"]
    assert failure["code"] == "duplicate" and "attachment" not in failure


def test_patch_attaches_files_as_one_undo_step(client, col):
    nid = client.post("/v1/notes", json=note("犬")).json()["created"][0]["id"]
    body = {"fields": {"Back": "dog"},
            "audio": {"data": b64(b"mp3"), "filename": "inu.mp3", "fields": ["Back"]},
            "picture": {"data": b64(b"png"), "filename": "inu.png", "fields": ["Front", "Back"]}}
    r = client.patch(f"/v1/notes/{nid}", json=body)
    assert r.status_code == 200, r.text
    # Appended after `fields` is applied, audio first, as on creation.
    assert fields_of(col, nid) == {"Front": '犬<img src="inu.png">',
                                   "Back": 'dog[sound:inu.mp3]<img src="inu.png">'}
    assert col.media.have("inu.mp3") and col.media.have("inu.png")
    assert col.undo_status().undo == "Update Note"
    col.undo()
    assert fields_of(col, nid) == {"Front": "犬", "Back": "meaning"}


def test_patch_follows_a_renamed_file(client, col):
    col.media.write_data("same.png", b"already here")
    nid = client.post("/v1/notes", json=note("犬")).json()["created"][0]["id"]
    client.patch(f"/v1/notes/{nid}", json={"picture": {"data": b64(b"new"), "filename": "same.png", "fields": ["Back"]}})
    back = fields_of(col, nid)["Back"]
    assert back.startswith('meaning<img src="') and 'src="same.png"' not in back
    stored = back[len('meaning<img src="'):-2]
    assert col.media.have(stored)


@pytest.mark.parametrize("files,message", [
    ({"picture": [{"data": b64(b"ok"), "filename": "ok.png"}, {"data": "not base64!", "filename": "bad.png"}]},
     "picture 1 (bad.png): 'data' is not valid base64"),
    ({"audio": {"data": b64(b"ok"), "filename": "ok.mp3", "fields": ["Missing"]}}, "Unknown field 'Missing'"),
])
def test_a_bad_file_on_patch_changes_nothing(client, col, files, message):
    nid = client.post("/v1/notes", json=note("犬")).json()["created"][0]["id"]
    r = client.patch(f"/v1/notes/{nid}", json={"fields": {"Back": "dog"}, **files})
    assert r.status_code == 400 and message in r.json()["detail"], r.text
    assert fields_of(col, nid)["Back"] == "meaning"
    assert not any(col.media.have(n) for n in ("ok.png", "bad.png", "ok.mp3"))


def test_patch_skips_a_reference_the_field_has(client, col):
    nid = client.post("/v1/notes", json=note("犬")).json()["created"][0]["id"]
    body = {"audio": {"data": b64(b"mp3"), "filename": "inu.mp3", "fields": ["Back"]},
            "picture": {"data": b64(b"png"), "filename": "inu.png", "fields": ["Front"]}}
    client.patch(f"/v1/notes/{nid}", json={**body, "fields": {"Front": '<img src="inu.png">犬'}})
    client.patch(f"/v1/notes/{nid}", json=body)   # a retry
    assert fields_of(col, nid) == {"Front": '<img src="inu.png">犬', "Back": "meaning[sound:inu.mp3]"}
    # A file Anki renames is a different reference, so it is added.
    client.patch(f"/v1/notes/{nid}", json={"audio": {"data": b64(b"other"), "filename": "inu.mp3", "fields": ["Back"]}})
    back = fields_of(col, nid)["Back"]
    assert back.startswith("meaning[sound:inu.mp3][sound:inu") and back.count("[sound:") == 2


def test_same_named_files_each_keep_their_own_reference(client, col):
    # Review finding 2026-10-01: a rename replaced every matching reference.
    col.media.write_data("image.png", b"already here")
    body = note("犬", picture=[{"data": b64(b"first"), "filename": "image.png", "fields": ["Back"]},
                               {"data": b64(b"second"), "filename": "image.png", "fields": ["Back"]}])
    body["fields"]["Back"] = 'mine:<img src="image.png">'   # the client means the existing file
    created = client.post("/v1/notes", json=body).json()["created"][0]
    first, second = (f["filename"] for f in created["files"])
    assert len({first, second, "image.png"}) == 3
    assert fields_of(col, created["id"])["Back"] == (
        f'mine:<img src="image.png"><img src="{first}"><img src="{second}">')
    assert col.media.have(first) and col.media.have(second)
