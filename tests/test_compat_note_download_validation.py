"""Note downloads respect early validation and later option/duplicate checks."""

from pathlib import Path

import pytest
from test_compat_downloads import download_requests as download_requests
from test_compat_downloads import download_url as download_url


def submit(client, action, note):
    plural = action in ("addNotes", "canAddNotes", "canAddNotesWithErrorDetail")
    params = {"notes": [note]} if plural else {"note": note}
    return client.post("/", json={"action": action, "version": 6, "params": params}).json()


def assert_rejected(reply, action):
    if action in ("addNote", "addNotes"):
        assert reply["result"] is None
        assert reply["error"]
    else:
        assert reply["error"] is None
        result = reply["result"]
        if action in ("canAddNotes", "canAddNotesWithErrorDetail"):
            assert len(result) == 1
            result = result[0]
        if "WithErrorDetail" in action:
            assert result["canAdd"] is False
            assert result["error"]
        else:
            assert result is False


@pytest.mark.parametrize("action", [
    "addNote", "addNotes", "canAddNote", "canAddNotes",
    "canAddNoteWithErrorDetail", "canAddNotesWithErrorDetail",
])
@pytest.mark.parametrize("invalid", ["model", "deck", "fields", "missing_fields"])
def test_invalid_note_does_not_download(client, col, download_url, download_requests, action, invalid):
    note = {
        "modelName": "Basic", "deckName": "Default", "fields": {"Front": "validation probe"},
        "audio": {"filename": "probe.mp3", "url": download_url + "/200/declared", "fields": ["Back"]},
    }
    if invalid == "model":
        note["modelName"] = "Missing download probe model"
    elif invalid == "deck":
        note["deckName"] = "Missing download probe deck"
    elif invalid == "fields":
        note["fields"] = None
    else:
        del note["fields"]
    assert_rejected(submit(client, action, note), action)
    assert download_requests == []
    assert list(Path(col.media.dir()).iterdir()) == []
    assert col.find_notes('"Front:validation probe"') == []
    assert col.decks.by_name("Missing download probe deck") is None


@pytest.mark.parametrize("action", ["addNote", "canAddNotes", "canAddNotesWithErrorDetail"])
@pytest.mark.parametrize("invalid", ["options", "duplicate", "empty"])
def test_late_note_checks_keep_download_side_effects(
    client, col, download_url, download_requests, action, invalid,
):
    front = "late validation probe"
    if invalid == "duplicate":
        existing = col.new_note(col.models.by_name("Basic"))
        existing["Front"] = front
        col.add_note(existing, col.decks.id("Default"))
    before = col.find_notes("")
    note = {
        "modelName": "Basic", "deckName": "Default",
        "fields": {"Front": "" if invalid == "empty" else front},
        "audio": {"filename": "late.mp3", "url": download_url + "/200/declared", "fields": ["Back"]},
    }
    if invalid == "options":
        note["options"] = {"allowDuplicate": 1}
    assert_rejected(submit(client, action, note), action)
    assert download_requests == ["/200/declared"]
    assert Path(col.media.dir(), "late.mp3").read_bytes() == b"payload"
    assert col.find_notes("") == before
