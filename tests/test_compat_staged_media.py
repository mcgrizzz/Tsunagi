"""Storage and field handling determine whether the next URL is fetched."""

from pathlib import Path

import pytest
from test_compat_downloads import download_requests as download_requests
from test_compat_downloads import download_url as download_url


@pytest.mark.parametrize("action", ["addNote", "updateNoteFields", "canAddNoteWithErrorDetail"])
@pytest.mark.parametrize("fields", [None, [], {"Back": 1}])
def test_storage_result_precedes_next_download(
    client, col, monkeypatch, download_url, download_requests, action, fields,
):
    from tsunagi.http.compat import downloads

    events = []
    write = col.media.write_data
    fetch = downloads.download_media

    def record_write(filename, data, *args, **kwargs):
        events.append(("write", filename))
        if filename == "failed.mp3":
            raise OSError("storage <failed> & unavailable")
        return write(filename, data, *args, **kwargs)

    def record_fetch(url):
        events.append(("download", "suffix.mp3"))
        return fetch(url)

    monkeypatch.setattr(col.media, "write_data", record_write)
    monkeypatch.setattr(downloads, "download_media", record_fetch)
    spec = {
        "modelName": "Basic", "deckName": "Default",
        "fields": {"Front": "staged media probe", "Back": "updated"},
        "audio": [
            {"filename": "prefix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
            {"filename": "failed.mp3", "data": "YXVkaW8=", "fields": fields},
        ],
        "video": [{"filename": "suffix.mp3", "url": download_url + "/200/declared", "fields": ["Back"]}],
    }
    if action == "updateNoteFields":
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"], note["Back"] = "staged media probe", "original"
        col.add_note(note, col.decks.id("Default"))
        spec["id"] = note.id
    before = col.find_notes("")
    reply = client.post("/", json={"action": action, "version": 6, "params": {"note": spec}}).json()
    expected_events = [("write", "prefix.mp3"), ("write", "failed.mp3")]
    if fields is not None:
        expected_events += [("download", "suffix.mp3"), ("write", "suffix.mp3")]
    # No storage is retried when the final note operation replays the results.
    assert events == expected_events
    assert download_requests == ([] if fields is None else ["/200/declared"])
    assert Path(col.media.dir(), "prefix.mp3").read_bytes() == b"audio"
    assert not Path(col.media.dir(), "failed.mp3").exists()
    suffix = Path(col.media.dir(), "suffix.mp3")
    assert suffix.exists() == (fields is not None)
    if fields is None:
        error = "'NoneType' object is not iterable"
        if action == "canAddNoteWithErrorDetail":
            assert reply == {"result": {"canAdd": False, "error": error}, "error": None}
        else:
            assert reply == {"result": None, "error": error}
        assert col.find_notes("") == before
        if action == "updateNoteFields":
            assert col.get_note(note.id)["Back"] == "original"
    else:
        assert reply["error"] is None
        assert suffix.read_bytes() == b"payload"
        if action == "canAddNoteWithErrorDetail":
            assert reply["result"] == {"canAdd": True}
            assert col.find_notes("") == before
        else:
            note_id = reply["result"] if action == "addNote" else note.id
            message = "storage &lt;failed&gt; &amp; unavailable" if fields else ""
            assert col.get_note(note_id)["Back"] == (
                "updated[sound:prefix.mp3]" + message + "[sound:suffix.mp3]"
            )


def test_field_append_failure_stops_download_after_storing_file(
    client, col, download_url, download_requests,
):
    reply = client.post("/", json={"action": "canAddNoteWithErrorDetail", "version": 6, "params": {"note": {
        "modelName": "Basic", "deckName": "Default", "fields": {"Front": "bad field probe", "Back": None},
        "audio": [
            {"filename": "stored.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
            {"filename": "suffix.mp3", "url": download_url + "/200/declared", "fields": ["Back"]},
        ],
    }}}).json()
    assert reply["error"] is None
    assert reply["result"]["canAdd"] is False
    assert "NoneType" in reply["result"]["error"]
    assert download_requests == []
    assert Path(col.media.dir(), "stored.mp3").read_bytes() == b"audio"
    assert not Path(col.media.dir(), "suffix.mp3").exists()
    assert col.find_notes("") == []
