"""Update downloads follow note/field validation and precede tag validation."""

from pathlib import Path

import pytest
from test_compat_downloads import download_requests as download_requests
from test_compat_downloads import download_url as download_url


@pytest.fixture
def update_target(col):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"], note["Back"] = "update download probe", "original"
    note.tags = ["original"]
    col.add_note(note, col.decks.id("Default"))
    return note.id


def submit(client, action, spec):
    return client.post("/", json={"action": action, "version": 6, "params": {"note": spec}}).json()


def update_spec(note_id, url):
    return {
        "id": note_id, "fields": {"Back": "updated"},
        "audio": {"filename": "update.mp3", "url": url + "/200/declared", "fields": ["Back"]},
    }


@pytest.mark.parametrize("action", ["updateNoteFields", "updateNote"])
@pytest.mark.parametrize("invalid", ["missing_id", "null_id", "null_fields", "list_fields", "missing_fields"])
def test_invalid_update_skips_download(
    client, col, update_target, download_url, download_requests, action, invalid,
):
    spec = update_spec(update_target, download_url)
    if invalid == "missing_id":
        spec["id"] = 0
    elif invalid == "null_id":
        spec["id"] = None
    elif invalid == "null_fields":
        spec["fields"] = None
    elif invalid == "list_fields":
        spec["fields"] = []
    else:
        del spec["fields"]
    reply = submit(client, action, spec)
    assert reply["result"] is None
    assert reply["error"]
    assert download_requests == []
    assert list(Path(col.media.dir()).iterdir()) == []
    note = col.get_note(update_target)
    assert note["Back"] == "original"
    assert note.tags == ["original"]


@pytest.mark.parametrize("action", ["updateNoteFields", "updateNote"])
def test_valid_update_keeps_exact_case_fields_and_download(
    client, col, update_target, download_url, download_requests, action,
):
    spec = update_spec(update_target, download_url)
    spec["fields"] = {"back": "ignored", "Unknown": "ignored"}
    assert submit(client, action, spec) == {"result": None, "error": None}
    assert download_requests == ["/200/declared"]
    assert Path(col.media.dir(), "update.mp3").read_bytes() == b"payload"
    assert col.get_note(update_target)["Back"] == "original[sound:update.mp3]"


def test_update_tag_error_keeps_field_and_media_changes(
    client, col, update_target, download_url, download_requests,
):
    spec = update_spec(update_target, download_url)
    spec["tags"] = None
    reply = submit(client, "updateNote", spec)
    assert reply["result"] is None
    assert reply["error"]
    assert download_requests == ["/200/declared"]
    assert Path(col.media.dir(), "update.mp3").read_bytes() == b"payload"
    note = col.get_note(update_target)
    assert note["Back"] == "updated[sound:update.mp3]"
    assert note.tags == ["original"]


def test_tags_only_update_does_not_process_media(
    client, col, update_target, download_url, download_requests,
):
    spec = update_spec(update_target, download_url)
    del spec["fields"]
    spec["tags"] = ["changed"]
    assert submit(client, "updateNote", spec) == {"result": None, "error": None}
    assert download_requests == []
    assert list(Path(col.media.dir()).iterdir()) == []
    note = col.get_note(update_target)
    assert note["Back"] == "original"
    assert note.tags == ["changed"]


@pytest.mark.parametrize("removed", [False, True])
def test_update_reloads_note_after_download(
    client, col, update_target, download_url, download_requests, monkeypatch, removed,
):
    from tsunagi.http.compat import downloads

    fetch = downloads.download_media

    def fetch_then_change_note(url):
        data = fetch(url)
        if removed:
            col.remove_notes([update_target])
        else:
            note = col.get_note(update_target)
            note["Front"] = "edited during download"
            col.update_note(note)
        return data

    monkeypatch.setattr(downloads, "download_media", fetch_then_change_note)
    reply = submit(client, "updateNoteFields", update_spec(update_target, download_url))
    assert download_requests == ["/200/declared"]
    media = Path(col.media.dir(), "update.mp3")
    if removed:
        assert reply["result"] is None
        assert reply["error"]
        assert col.find_notes("") == []
        assert not media.exists()
    else:
        assert reply == {"result": None, "error": None}
        assert media.read_bytes() == b"payload"
        note = col.get_note(update_target)
        assert note["Front"] == "edited during download"
        assert note["Back"] == "updated[sound:update.mp3]"
