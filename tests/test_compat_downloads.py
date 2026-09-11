"""Compatibility HTTP downloads and preserved native/resource-limit behavior."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from tsunagi.http.v1.media import _fetch_url


@pytest.fixture
def download_requests():
    return []


@pytest.fixture
def download_url(download_requests):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            download_requests.append(self.path)
            status, length = self.path.strip("/").split("/")
            self.send_response(int(status))
            if length == "declared":
                self.send_header("Content-Length", "7")
            self.end_headers()
            self.wfile.write(b"payload")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("status", [201, 202, 204, 206, 404, 500])
def test_failed_download_keeps_existing_file(client, col, download_url, status):
    col.media.write_data("existing.mp3", b"original")
    url = f"{download_url}/{status}/declared"
    response = client.post("/", json={"action": "storeMediaFile", "version": 6, "params": {
        "filename": "existing.mp3", "url": url,
    }})
    assert response.json() == {"result": None, "error": f"{url} download failed with return code {status}"}
    assert (Path(col.media.dir()) / "existing.mp3").read_bytes() == b"original"


@pytest.mark.parametrize("length", ["declared", "undeclared"])
def test_compat_download_retains_size_limit(client, col, reset_settings, download_url, length):
    reset_settings.update(media_max_bytes=4)
    col.media.write_data("limited.mp3", b"original")
    response = client.post("/", json={"action": "storeMediaFile", "version": 6, "params": {
        "filename": "limited.mp3", "url": f"{download_url}/200/{length}",
    }})
    assert response.json() == {"result": None, "error": "file exceeds media_max_bytes (4)"}
    assert (Path(col.media.dir()) / "limited.mp3").read_bytes() == b"original"


def test_native_download_still_accepts_201(download_url):
    assert _fetch_url(download_url + "/201/declared") == b"payload"


@pytest.mark.parametrize("action", ["addNote", "canAddNotes", "canAddNotesWithErrorDetail"])
def test_note_downloads_follow_attachment_order(
    client, col, download_url, download_requests, action,
):
    note = {
        "deckName": "Default", "modelName": "Basic",
        "fields": {"Front": "ordered downloads", "Back": ""},
        "audio": [
            {"filename": "first.mp3", "url": download_url + "/200/declared", "fields": ["Back"]},
            {"filename": "second.mp3", "url": download_url + "/200/undeclared", "fields": ["Back"]},
        ],
    }
    params = {"note": note} if action == "addNote" else {"notes": [note]}
    reply = client.post("/", json={"action": action, "version": 6, "params": params}).json()
    assert reply["error"] is None
    assert download_requests == ["/200/declared", "/200/undeclared"]
    for filename in ("first.mp3", "second.mp3"):
        assert Path(col.media.dir(), filename).read_bytes() == b"payload"
    ids = col.find_notes('"Front:ordered downloads"')
    if action == "addNote":
        assert ids == [reply["result"]]
        assert col.get_note(ids[0])["Back"] == "[sound:first.mp3][sound:second.mp3]"
    else:
        assert ids == []


@pytest.mark.parametrize("replacement,skip_hash,expected_files", [
    ("false", False, {b"audio"}),
    ([], False, {b"original", b"audio"}),
    ([1], False, {b"audio"}),
    ({}, False, {b"original", b"audio"}),
    ("false", True, {b"original"}),
])
@pytest.mark.parametrize("action", ["storeMediaFile", "canAddNote"])
def test_media_replacement_preserves_raw_option_values(
    client, col, action, replacement, skip_hash, expected_files,
):
    col.media.write_data("options.mp3", b"original")
    media = {"filename": "options.mp3", "data": "YXVkaW8=", "deleteExisting": replacement}
    if skip_hash:
        media["skipHash"] = "a5ca0b5894324f8bb54bb9fffad29d1e"
    params = media if action == "storeMediaFile" else {"note": {
        "deckName": "Default", "modelName": "Basic",
        "fields": {"Front": "media options probe", "Back": ""},
        "audio": {**media, "fields": ["Back"]},
    }}
    reply = client.post("/", json={"action": action, "version": 6, "params": params}).json()
    assert reply["error"] is None
    if action == "canAddNote":
        assert reply["result"] is True
        assert col.find_notes('"Front:media options probe"') == []
    elif skip_hash:
        assert reply["result"] is None
    else:
        assert Path(col.media.dir(), reply["result"]).read_bytes() == b"audio"
    files = list(Path(col.media.dir()).glob("*.mp3"))
    assert len(files) == len(expected_files)
    assert {path.read_bytes() for path in files} == expected_files


@pytest.mark.parametrize("selection,data,error,back", [
    ({}, "YXVkaW8=", None, "updated"),
    ({"fields": None}, "YXVkaW8=", None, "updated"),
    ({"fields": "Back"}, "YXVkaW8=", None, "updated"),
    ({"fields": {"Back": 1}}, "YXVkaW8=", None, "updated"),
    ({"fields": []}, "AA", None, "updated"),
    ({}, "AA", "'fields'", "original"),
    ({"fields": None}, "AA", "'NoneType' object is not iterable", "original"),
    ({"fields": {"Back": 1}}, "AA", None, "updatedIncorrect padding"),
    ({"fields": ["Back", "Back"]}, "AA", None, "updatedIncorrect paddingIncorrect padding"),
])
def test_media_field_selection_and_error_side_effects(client, col, selection, data, error, back):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"], note["Back"] = "media fields test", "original"
    col.add_note(note, col.decks.id("Default"))
    reply = client.post("/", json={"action": "updateNoteFields", "version": 6, "params": {
        "note": {"id": note.id, "fields": {"Back": "updated"}, "audio": {
            "filename": "selection.mp3", "data": data, **selection,
        }},
    }}).json()
    assert reply == {"result": None, "error": error}
    assert col.get_note(note.id)["Back"] == back
    media_file = Path(col.media.dir(), "selection.mp3")
    if data == "YXVkaW8=":
        assert media_file.read_bytes() == b"audio"
    else:
        assert not media_file.exists()


@pytest.mark.parametrize("params,error", [
    ({"filename": "raw.mp3", "data": False}, 'You must provide a "data", "path", or "url" field.'),
    ({"filename": "raw.mp3", "data": [1]}, "argument should be a bytes-like object or ASCII string, not 'list'"),
    ({"filename": 7, "data": "YXVkaW8="}, "bad argument type for built-in operation"),
])
def test_raw_store_values_do_not_create_files(client, col, params, error):
    reply = client.post("/", json={"action": "storeMediaFile", "version": 6, "params": params}).json()
    assert reply == {"result": None, "error": error}
    assert list(Path(col.media.dir()).iterdir()) == []


@pytest.mark.parametrize("malformed", [False, "malformed", ["malformed"]])
def test_raw_attachment_failure_preserves_earlier_media(client, col, malformed):
    # The shim preserves Python's error; its exact wording varies by version.
    with pytest.raises(TypeError) as native_error:
        malformed["filename"]
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"], note["Back"] = "raw attachment test", "original"
    col.add_note(note, col.decks.id("Default"))
    reply = client.post("/", json={"action": "updateNoteFields", "version": 6, "params": {
        "note": {"id": note.id, "fields": {"Back": "updated"}, "audio": [
            {"filename": "prefix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
            malformed,
            {"filename": "suffix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
        ]},
    }}).json()
    assert reply == {"result": None, "error": str(native_error.value)}
    assert col.get_note(note.id)["Back"] == "original"
    assert Path(col.media.dir(), "prefix.mp3").read_bytes() == b"audio"
    assert not Path(col.media.dir(), "suffix.mp3").exists()


@pytest.mark.parametrize("action", ["addNote", "addNotes", "canAddNotesWithErrorDetail", "updateNoteFields"])
@pytest.mark.parametrize("suffix_kind", ["audio", "picture"])
def test_malformed_attachment_stops_later_downloads(
    client, col, download_url, download_requests, action, suffix_kind,
):
    spec = {
        "deckName": "Default", "modelName": "Basic",
        "fields": {"Front": "download abort probe", "Back": "updated"},
        "audio": [
            {"filename": "prefix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
            False,
        ],
    }
    suffix = {"filename": "suffix.mp3", "url": download_url + "/200/declared", "fields": ["Back"]}
    spec.setdefault(suffix_kind, []).append(suffix)
    if action == "updateNoteFields":
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"], note["Back"] = "download abort probe", "original"
        col.add_note(note, col.decks.id("Default"))
        spec["id"] = note.id
    params = {"notes": [spec]} if action in ("addNotes", "canAddNotesWithErrorDetail") else {"note": spec}
    reply = client.post("/", json={"action": action, "version": 6, "params": params}).json()
    error = "'bool' object is not subscriptable"
    if action == "addNotes":
        assert reply == {"result": None, "error": str([error])}
    elif action == "canAddNotesWithErrorDetail":
        assert reply == {"result": [{"canAdd": False, "error": error}], "error": None}
    else:
        assert reply == {"result": None, "error": error}
    assert download_requests == []
    assert Path(col.media.dir(), "prefix.mp3").read_bytes() == b"audio"
    assert not Path(col.media.dir(), "suffix.mp3").exists()
    if action == "updateNoteFields":
        assert col.get_note(note.id)["Back"] == "original"
    else:
        assert col.find_notes('"Front:download abort probe"') == []
