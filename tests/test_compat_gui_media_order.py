"""GUI validation and storage must precede unreachable network requests."""

from pathlib import Path

import pytest
from test_compat_add_cards import add_dialog as add_dialog
from test_compat_add_cards import rpc
from test_compat_downloads import download_requests as download_requests
from test_compat_downloads import download_url as download_url


def spec(url):
    return {
        "deckName": "Default", "modelName": "Basic", "fields": {"Front": "GUI media probe"},
        "audio": {"filename": "suffix.mp3", "url": url + "/200/declared", "fields": ["Front"]},
    }


@pytest.mark.parametrize("action", ["guiAddCards", "guiAddNoteSetData"])
@pytest.mark.parametrize("invalid", ["deck", "model", "fields"])
def test_gui_validation_prevents_download(client, col, add_dialog, download_url, download_requests, action, invalid):
    note = spec(download_url)
    if invalid == "deck":
        note["deckName"] = "Missing GUI media deck"
    elif invalid == "model":
        note["modelName"] = "Missing GUI media model"
    else:
        note["fields"] = None
    reply = rpc(client, action, note=note)
    assert reply["result"] is None
    assert reply["error"]
    assert download_requests == []
    assert list(Path(col.media.dir()).iterdir()) == []
    assert add_dialog.callbacks == []


def test_partial_editor_change_precedes_error_without_download(
    client, col, add_dialog, download_url, download_requests,
):
    note = spec(download_url)
    note["fields"] = {"Front": "earlier change", "missing": "bad"}
    reply = rpc(client, "guiAddNoteSetData", note=note)
    assert reply == {"result": None, "error": 'Field "missing" not found in current note'}
    assert add_dialog.editor.note["Front"] == "earlier change"
    assert "load" not in add_dialog.events
    assert download_requests == []
    assert list(Path(col.media.dir()).iterdir()) == []


def test_append_tag_failure_precedes_download(client, col, add_dialog, download_url, download_requests):
    note = spec(download_url)
    note["tags"] = {}
    reply = rpc(client, "guiAddNoteSetData", note=note, append=True)
    assert reply == {"result": None, "error": "unhashable type: 'dict'"}
    assert add_dialog.editor.note["Front"] == "GUI media probe"
    assert download_requests == []
    assert list(Path(col.media.dir()).iterdir()) == []


@pytest.mark.parametrize("change", ["close", "replace_note", "replace_dialog"])
def test_changed_editor_stops_download_chain(
    client, col, add_dialog, monkeypatch, download_url, download_requests, change,
):
    from types import SimpleNamespace

    from tsunagi.http.compat import downloads

    fetch = downloads.download_media
    replacement = col.new_note(col.models.by_name("Basic"))
    replacement["Front"] = "replacement editor"

    def fetch_then_change_dialog(url):
        data = fetch(url)
        if change == "close":
            add_dialog.registry["AddCards"] = (None, None)
        elif change == "replace_note":
            add_dialog.editor.note = replacement
        else:
            add_dialog.registry["AddCards"] = (None, SimpleNamespace(editor=SimpleNamespace(note=replacement)))
        return data

    monkeypatch.setattr(downloads, "download_media", fetch_then_change_dialog)
    note = spec(download_url)
    note["audio"] = [note["audio"], {
        "filename": "second.mp3", "url": download_url + "/200/undeclared", "fields": ["Front"],
    }]
    reply = rpc(client, "guiAddNoteSetData", note=note)
    assert reply == {"result": {"error": "Add Note dialog is not open", "code": 1}, "error": None}
    assert download_requests == ["/200/declared"]
    assert list(Path(col.media.dir()).iterdir()) == []
    assert replacement["Front"] == "replacement editor"
    assert "load" not in add_dialog.events


@pytest.mark.parametrize("action", ["guiAddCards", "guiAddNoteSetData"])
@pytest.mark.parametrize("fatal", [False, True])
def test_gui_storage_result_controls_next_download(
    client, col, add_dialog, monkeypatch, download_url, download_requests, action, fatal,
):
    from tsunagi.http.compat import downloads

    events = []
    write = col.media.write_data
    fetch = downloads.download_media

    def record_write(filename, data):
        events.append(filename)
        if filename == "failed.mp3":
            raise OSError("storage failed")
        return write(filename, data)

    def record_fetch(url):
        events.append("download")
        return fetch(url)

    monkeypatch.setattr(col.media, "write_data", record_write)
    monkeypatch.setattr(downloads, "download_media", record_fetch)
    note = spec(download_url)
    suffix = note["audio"]
    note["audio"] = [
        {"filename": "prefix.mp3", "data": "YXVkaW8=", "fields": ["Front"]},
        {"filename": "failed.mp3", "data": "YXVkaW8=", "fields": None if fatal else ["Front"]},
        suffix,
    ]
    reply = rpc(client, action, note=note)
    assert events == ["prefix.mp3", "failed.mp3"] + ([] if fatal else ["download", "suffix.mp3"])
    assert download_requests == ([] if fatal else ["/200/declared"])
    assert Path(col.media.dir(), "prefix.mp3").read_bytes() == b"audio"
    assert not Path(col.media.dir(), "failed.mp3").exists()
    assert Path(col.media.dir(), "suffix.mp3").exists() == (not fatal)
    if fatal:
        assert reply == {"result": None, "error": "'NoneType' object is not iterable"}
    else:
        assert reply == {"result": 0 if action == "guiAddCards" else True, "error": None}
        for callback in add_dialog.callbacks:
            callback()
        assert add_dialog.editor.note["Front"] == (
            "GUI media probe[sound:prefix.mp3]storage failed[sound:suffix.mp3]"
        )
    assert col.find_notes("") == []
