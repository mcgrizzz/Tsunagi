"""Fatal media error handling must not fetch unreachable attachments."""

from pathlib import Path

import pytest
from test_compat_downloads import download_requests as download_requests
from test_compat_downloads import download_url as download_url


@pytest.mark.parametrize("action", ["updateNoteFields", "canAddNoteWithErrorDetail"])
@pytest.mark.parametrize("fault", ["decode", "download"])
@pytest.mark.parametrize("selection,error,repeats", [
    ({}, "'fields'", 0),
    ({"fields": None}, "'NoneType' object is not iterable", 0),
    ({"fields": False}, "'bool' object is not iterable", 0),
    ({"fields": 7}, "'int' object is not iterable", 0),
    ({"fields": []}, None, 0),
    ({"fields": "Back"}, None, 0),
    ({"fields": {"Back": 1}}, None, 1),
    ({"fields": ["Back", "Back"]}, None, 2),
])
def test_attachment_error_download_order(
    client, col, download_url, download_requests, action, fault, selection, error, repeats,
):
    spec = {
        "deckName": "Default", "modelName": "Basic",
        "fields": {"Front": "attachment abort probe", "Back": "updated"},
    }
    if action == "updateNoteFields":
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"], note["Back"] = "attachment abort probe", "original"
        col.add_note(note, col.decks.id("Default"))
        spec["id"] = note.id
    before = col.find_notes("")
    failed = {"filename": "failed.mp3", **selection}
    message = "Incorrect padding"
    expected_requests = []
    if fault == "decode":
        failed["data"] = "AA"
    else:
        failed["url"] = download_url + "/500/declared"
        message = failed["url"] + " download failed with return code 500"
        expected_requests.append("/500/declared")
    spec["audio"] = [
        {"filename": "prefix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
        failed,
    ]
    # The suffix is in another media kind, so an abort must stop the outer loop.
    spec["video"] = [{
        "filename": "suffix.mp3", "url": download_url + "/200/declared", "fields": ["Back"],
    }]
    reply = client.post("/", json={"action": action, "version": 6, "params": {"note": spec}}).json()
    if action == "updateNoteFields":
        assert reply == {"result": None, "error": error}
        expected_back = "original" if error else (
            "updated[sound:prefix.mp3]" + message * repeats + "[sound:suffix.mp3]"
        )
        assert col.get_note(note.id)["Back"] == expected_back
    else:
        result = {"canAdd": False, "error": error} if error else {"canAdd": True}
        assert reply == {"result": result, "error": None}
    if error is None:
        expected_requests.append("/200/declared")
    assert download_requests == expected_requests
    assert Path(col.media.dir(), "prefix.mp3").read_bytes() == b"audio"
    assert not Path(col.media.dir(), "failed.mp3").exists()
    suffix = Path(col.media.dir(), "suffix.mp3")
    assert suffix.exists() == (error is None)
    if error is None:
        assert suffix.read_bytes() == b"payload"
    assert col.find_notes("") == before
