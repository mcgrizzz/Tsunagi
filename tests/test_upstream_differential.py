"""Opt-in comparisons with real upstream code on equivalent real collections.

TSUNAGI_ANKICONNECT_CHECKOUT=/path/to/pinned/checkout python -m pytest -q tests/test_upstream_differential.py
"""

import base64
import copy
import gzip
import hashlib
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest

from tools.upstream_reference import load_reference
from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc
from tsunagi.http.compat.signatures import SIGNATURES


@pytest.fixture(scope="module")
def upstream():
    checkout = os.environ.get("TSUNAGI_ANKICONNECT_CHECKOUT")
    if not checkout:
        pytest.skip("Set TSUNAGI_ANKICONNECT_CHECKOUT to run upstream comparisons")
    return load_reference(checkout)


@pytest.fixture()
def pair(col, client, tmp_path, upstream):
    from anki.collection import Collection

    model = col.models.by_name("Basic")
    deck = col.decks.id("Parity::日本語")
    for front, back, tags in [
        ("alpha", "one", ["root::child"]),
        ("beta", "two", ["other"]),
        ("gamma", "three", []),
    ]:
        note = col.new_note(model)
        note["Front"], note["Back"], note.tags = front, back, tags
        col.add_note(note, deck)
    reference_path = tmp_path / "reference.anki2"
    with sqlite3.connect(col.path) as source, sqlite3.connect(reference_path) as target:
        source.backup(target)
    reference_col = Collection(str(reference_path))
    upstream.collection = lambda: reference_col
    try:
        yield col, reference_col, upstream
    finally:
        reference_col.close()


def compare(pair, action, params=None, version=6):
    _, _, upstream = pair
    request = {"action": action, "version": version, "params": params or {}}
    reference_request = copy.deepcopy(request)
    if action == "requestPermission":
        # Match upstream's HTTP injection for a request without an Origin.
        reference_request["params"].update(origin="", allowed=True)
    expected = upstream.handler(reference_request)
    actual = handle_ankiconnect_rpc(copy.deepcopy(request))
    # JSON round trip reflects wire types (e.g. tuple/list, integer map keys).
    actual, expected = json.loads(json.dumps(actual)), json.loads(json.dumps(expected))
    if action == "getDeckStats":
        normalize_deck_stats(actual, pair[0])
        normalize_deck_stats(expected, pair[1])
    assert actual == expected, first_difference(actual, expected)
    return actual


def normalize_deck_stats(reply, collection):
    """Compare all stats, replacing independently allocated deck IDs by names."""
    if not isinstance(reply["result"], dict):
        return
    normalized = {}
    for did, row in reply["result"].items():
        full_name = collection.decks.get(int(did))["name"]
        row = dict(row)
        if "deck_id" in row:
            row["deck_id"] = full_name
        normalized[full_name] = row
    reply["result"] = normalized


def first_difference(actual, expected, path="response"):
    if type(actual) is not type(expected):
        return f"{path}: shim={actual!r}; upstream={expected!r}"[:1000]
    if isinstance(actual, dict):
        if actual.keys() != expected.keys():
            return f"{path} keys: shim={list(actual)}; upstream={list(expected)}"
        for key in actual:
            if actual[key] != expected[key]:
                return first_difference(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path} length: shim={len(actual)}; upstream={len(expected)}"
        for index, (left, right) in enumerate(zip(actual, expected)):
            if left != right:
                return first_difference(left, right, f"{path}[{index}]")
    return f"{path}: shim={actual!r}; upstream={expected!r}"[:1000]


@pytest.mark.parametrize("action,params", [
    ("version", {}),
    ("apiReflect", {"scopes": ["actions"]}),
    ("apiReflect", {"scopes": []}),
    ("apiReflect", {}),
    ("apiReflect", {"scopes": "actions"}),
    ("apiReflect", {"scopes": [], "actions": "version"}),
    ("apiReflect", {"scopes": ["actions"], "actions": [1]}),
    ("deckNames", {}),
    ("deckNamesAndIds", {}),
    ("modelNames", {}),
    ("modelNamesAndIds", {}),
    ("getTags", {}),
    ("getNumCardsReviewedToday", {}),
    ("getNumCardsReviewedByDay", {}),
    ("getMediaFilesNames", {"pattern": "*"}),
    ("findNotes", {"query": "invalidProperty:bad"}),
    ("modelFieldNames", {"modelName": "Basic"}),
    ("modelFieldDescriptions", {"modelName": "Basic"}),
    ("modelFieldFonts", {"modelName": "Basic"}),
    ("modelFieldsOnTemplates", {"modelName": "Basic"}),
    ("modelStyling", {"modelName": "Basic"}),
    ("modelTemplates", {"modelName": "Basic"}),
    ("getDeckConfig", {"deck": "Default"}),
    ("getDeckStats", {"decks": ["Default"]}),
    ("getDeckStats", {"decks": ["Parity::日本語"]}),
])
def test_read_actions(pair, action, params):
    compare(pair, action, params)


@pytest.mark.parametrize("query", [
    "", 'deck:"Parity::日本語"', "tag:root::*", "-tag:other", "Front:alpha",
    "(Front:alpha OR Front:beta) -tag:other", "is:new", "prop:ivl=0",
    '"Front:re:^(alpha|beta)$"', "nid:0", "rated:1", "added:1",
    "(", "prop:ivl=nope",
])
@pytest.mark.parametrize("action", ["findCards", "findNotes"])
def test_search_expressions(pair, action, query):
    compare(pair, action, {"query": query})


@pytest.mark.parametrize("action", [
    "cardsInfo", "cardsModTime", "cardsToNotes", "areSuspended", "getEaseFactors",
    "getIntervals", "areDue", "getReviewsOfCards", "getDecks",
])
def test_card_lists(pair, action):
    cards = pair[0].find_cards("")
    compare(pair, action, {"cards": [cards[-1], cards[0], cards[-1]]})


@pytest.mark.parametrize("action", ["notesInfo", "notesModTime"])
def test_note_lists(pair, action):
    notes = pair[0].find_notes("")
    compare(pair, action, {"notes": [notes[-1], notes[0], notes[-1], 0]})


@pytest.mark.parametrize("action,parameter", [
    ("cardsInfo", "cards"),
    ("notesInfo", "notes"),
    ("getReviewsOfCards", "cards"),
])
def test_batch_boundary(pair, action, parameter):
    ids = pair[0].find_cards("") if parameter == "cards" else pair[0].find_notes("")
    compare(pair, action, {parameter: [ids[0]] * 1000 + [ids[-1], 0]})


@pytest.mark.parametrize("add", [True, False])
def test_tag_side_effects(pair, add):
    notes = list(pair[0].find_notes(""))
    compare(pair, "addTags", {"notes": notes, "tags": "root::child extra", "add": add})
    assert [pair[0].get_note(nid).tags for nid in notes] == [pair[1].get_note(nid).tags for nid in notes]


def test_suspend_side_effects(pair):
    cards = list(pair[0].find_cards(""))
    compare(pair, "suspend", {"cards": cards})
    assert [pair[0].get_card(cid).queue for cid in cards] == [pair[1].get_card(cid).queue for cid in cards]
    compare(pair, "unsuspend", {"cards": cards})
    assert [pair[0].get_card(cid).queue for cid in cards] == [pair[1].get_card(cid).queue for cid in cards]


@pytest.mark.parametrize("version", [1, 4, 5, 6])
def test_protocol_versions(pair, version):
    compare(pair, "version", version=version)


@pytest.mark.parametrize("action,params", [
    ("version", {"unexpected": True}),
    ("findCards", {}),
    ("findCards", {"query": None}),
    ("findCards", {"query": 123}),
    ("notesInfo", {}),
    ("notesInfo", {"notes": None}),
    ("cardsInfo", {"cards": None}),
    ("notAnAction", {}),
])
def test_argument_errors(pair, action, params):
    compare(pair, action, params)


@pytest.mark.parametrize("action,parameter", [
    ("cardsInfo", "cards"), ("cardsModTime", "cards"),
    ("notesModTime", "notes"),
    ("notesInfo", "notes"),
    ("getDecks", "cards"),
    ("getReviewsOfCards", "cards"),
])
def test_missing_ids(pair, action, parameter):
    compare(pair, action, {parameter: [9999999999999]})


def test_cards_batch_without_zero_id(pair):
    cards = pair[0].find_cards("")
    compare(pair, "cardsInfo", {"cards": [cards[0]] * 1000 + [cards[-1], 9999999999999]})


def test_media_roundtrip_and_side_effects(pair):
    filename = "parity-音声.txt"
    payload = b"parity media payload"
    compare(pair, "storeMediaFile", {"filename": filename, "data": base64.b64encode(payload).decode()})
    for collection in pair[:2]:
        assert (Path(collection.media.dir()) / filename).read_bytes() == payload
    compare(pair, "retrieveMediaFile", {"filename": filename})
    compare(pair, "getMediaFilesNames", {"pattern": "parity-*"})
    compare(pair, "deleteMediaFile", {"filename": filename})
    for collection in pair[:2]:
        assert not (Path(collection.media.dir()) / filename).exists()
    compare(pair, "retrieveMediaFile", {"filename": filename})


def media_state(collection):
    root = Path(collection.media.dir())
    return {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}


def note_state(collection):
    return [
        (nid, note.mid, list(note.fields), list(note.tags), list(collection.card_ids_of_note(nid)))
        for nid in collection.find_notes("")
        for note in [collection.get_note(nid)]
    ]


def assert_note_and_media_state(pair):
    assert note_state(pair[0]) == note_state(pair[1])
    assert media_state(pair[0]) == media_state(pair[1])


@pytest.mark.parametrize("delete_existing", [True, False, None])
def test_media_collision_semantics(pair, delete_existing):
    for collection in pair[:2]:
        collection.media.write_data("collision.txt", b"original")
    compare(pair, "storeMediaFile", {
        "filename": "collision.txt", "data": base64.b64encode(b"replacement").decode(),
        "deleteExisting": delete_existing,
    })
    assert media_state(pair[0]) == media_state(pair[1])


def test_media_skip_hash_preserves_existing_file(pair):
    for collection in pair[:2]:
        collection.media.write_data("skip.txt", b"original")
    payload = b"skip this payload"
    compare(pair, "storeMediaFile", {
        "filename": "skip.txt", "data": base64.b64encode(payload).decode(),
        "skipHash": hashlib.md5(payload).hexdigest(),
    })
    assert media_state(pair[0]) == media_state(pair[1]) == {"skip.txt": b"original"}


@pytest.mark.parametrize("data", [None, "", "AA", "!!!"])
def test_media_invalid_data(pair, data):
    compare(pair, "storeMediaFile", {"filename": "invalid.txt", "data": data})
    assert media_state(pair[0]) == media_state(pair[1])


@pytest.mark.parametrize("allow_local_path", [
    True,
    pytest.param(False, marks=pytest.mark.xfail(
        strict=True, raises=AssertionError,
        reason="D11: Tsunagi's local-path gate is disabled by default; upstream allows local paths",
    )),
])
def test_media_local_path(pair, tmp_path, reset_settings, allow_local_path):
    from tsunagi.adapters.config import DEFAULTS

    config = copy.deepcopy(DEFAULTS)
    config["gates"]["media_allow_local_path"] = allow_local_path
    reset_settings.configure(config, persist=None)
    path = tmp_path / "source.txt"
    path.write_bytes(b"local path payload")
    compare(pair, "storeMediaFile", {"filename": "from-path.txt", "path": str(path)})
    assert media_state(pair[0]) == media_state(pair[1])


def test_media_data_precedes_path(pair, tmp_path):
    path = tmp_path / "source.txt"
    path.write_bytes(b"path should not win")
    compare(pair, "storeMediaFile", {
        "filename": "precedence.txt", "path": str(path),
        "data": base64.b64encode(b"data wins").decode(),
    })
    assert media_state(pair[0]) == media_state(pair[1]) == {"precedence.txt": b"data wins"}


@pytest.fixture()
def media_url():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b"local HTTP media payload"
            query = parse_qs(urlsplit(self.path).query)
            if "disconnect" in query:
                self.connection.close()
                return
            fault = query.get("fault", [""])[0]
            if fault == "redirect-loop":
                self.send_response(302)
                self.send_header("Location", self.path)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = int(query.get("status", ["200"])[0])
            self.send_response(status)
            if status in (301, 302, 303, 307, 308):
                self.send_header("Location", "/media")
            if fault in ("gzip", "invalid-gzip"):
                self.send_header("Content-Encoding", "gzip")
                payload = gzip.compress(payload) if fault == "gzip" else b"not gzip data"
            if fault == "empty":
                payload = b""
            if fault == "chunked-truncated":
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"10\r\nshort")
            else:
                length = len(payload) + (10 if fault == "truncated" else 0)
                self.send_header("Content-Length", str(length))
                self.end_headers()
                self.wfile.write(payload)
            self.close_connection = True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/media"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_media_url(pair, media_url):
    compare(pair, "storeMediaFile", {"filename": "from-url.txt", "url": media_url})
    assert media_state(pair[0]) == media_state(pair[1]) == {"from-url.txt": b"local HTTP media payload"}


@pytest.mark.parametrize("status", [200, 201, 202, 204, 206, 301, 302, 303, 307, 308, 400, 403, 404, 429, 500])
@pytest.mark.parametrize("action", ["storeMediaFile", "updateNoteFields", "canAddNote"])
def test_media_http_status_and_nested_errors(pair, media_url, status, action):
    for collection in pair[:2]:
        collection.media.write_data("status.mp3", b"original")
    media = {"filename": "status.mp3", "url": f"{media_url}?status={status}", "deleteExisting": True}
    if action == "storeMediaFile":
        params = media
    elif action == "updateNoteFields":
        params = {"note": {"id": pair[0].find_notes("")[0], "fields": {"Back": "updated"},
                           "audio": {**media, "fields": ["Back"]}}}
    else:
        params = {"note": {"deckName": "Default", "modelName": "Basic",
                           "fields": {"Front": "download probe", "Back": "back"},
                           "audio": {**media, "fields": ["Back"]}}}
    compare(pair, action, params)
    assert_note_and_media_state(pair)
    expected = b"local HTTP media payload" if status in (200, 301, 302, 303, 307, 308) else b"original"
    assert media_state(pair[0]) == {"status.mp3": expected}


@pytest.mark.parametrize("fault", [
    "truncated", "chunked-truncated", "invalid-gzip", "redirect-loop", "gzip", "empty",
])
@pytest.mark.parametrize("action", ["storeMediaFile", "updateNoteFields", "canAddNote"])
def test_media_transport_edges_preserve_collection_state(pair, media_url, fault, action):
    for collection in pair[:2]:
        collection.media.write_data("transport.mp3", b"original")
    media = {"filename": "transport.mp3", "url": f"{media_url}?fault={fault}",
             "deleteExisting": True}
    if action == "storeMediaFile":
        params = media
    elif action == "updateNoteFields":
        params = {"note": {"id": pair[0].find_notes("")[0], "fields": {"Back": "updated"},
                           "audio": {**media, "fields": ["Back"]}}}
    else:
        params = {"note": {"deckName": "Default", "modelName": "Basic",
                           "fields": {"Front": "transport probe", "Back": "back"},
                           "audio": {**media, "fields": ["Back"]}}}
    compare(pair, action, params)
    assert_note_and_media_state(pair)
    expected = {"gzip": b"local HTTP media payload", "empty": b""}.get(fault, b"original")
    assert media_state(pair[0]) == {"transport.mp3": expected}


def assert_media_url_failure(pair, url, action):
    media = {"filename": "invalid-url.mp3", "url": url}
    params = media if action == "storeMediaFile" else {"note": {
        "id": pair[0].find_notes("")[0], "fields": {"Back": "updated"},
        "audio": {**media, "fields": ["Back"]},
    }}
    compare(pair, action, params)
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("url", [
    "not-a-url", "http://", "https://", "://", "ftp://127.0.0.1/media", "file:///missing-media",
])
@pytest.mark.parametrize("action", ["storeMediaFile", "updateNoteFields"])
def test_media_invalid_urls(pair, url, action):
    assert_media_url_failure(pair, url, action)


@pytest.mark.parametrize("action", ["storeMediaFile", "updateNoteFields"])
def test_media_disconnected_download(pair, media_url, action):
    assert_media_url_failure(pair, media_url + "?disconnect=1", action)


def test_nested_download_error_escapes_url(pair, media_url):
    assert_media_url_failure(pair, media_url + '?status=404&label=<tag>"quote"', "updateNoteFields")


_MEDIA_REPLACEMENT_OPTIONS = [
    {}, {"deleteExisting": None}, {"deleteExisting": False}, {"deleteExisting": True},
    {"deleteExisting": 0}, {"deleteExisting": "false"}, {"deleteExisting": ""},
    {"deleteExisting": []}, {"deleteExisting": [1]}, {"deleteExisting": {"value": False}},
    {"deleteExisting": True, "skipHash": "a5ca0b5894324f8bb54bb9fffad29d1e"},
    {"deleteExisting": "false", "skipHash": "a5ca0b5894324f8bb54bb9fffad29d1e"},
]


@pytest.mark.parametrize("options", _MEDIA_REPLACEMENT_OPTIONS)
@pytest.mark.parametrize("kind", ["audio", "video", "picture"])
@pytest.mark.parametrize("action", ["updateNoteFields", "canAddNote"])
def test_nested_media_replacement_options(pair, options, kind, action):
    for collection in pair[:2]:
        collection.media.write_data("nested-media.mp3", b"original")
    media = {"filename": "nested-media.mp3", "data": "YXVkaW8=",
             "fields": ["Back", "Unknown", "Back"], **options}
    if action == "updateNoteFields":
        note = {"id": pair[0].find_notes("")[0], "fields": {"Back": "updated"}, kind: media}
    else:
        note = {"deckName": "Default", "modelName": "Basic",
                "fields": {"Front": "nested media probe", "Back": "back"}, kind: media}
    compare(pair, action, {"note": note})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("options", _MEDIA_REPLACEMENT_OPTIONS)
def test_media_replacement_option_values(pair, options):
    for collection in pair[:2]:
        collection.media.write_data("replacement.mp3", b"original")
    compare(pair, "storeMediaFile", {"filename": "replacement.mp3", "data": "YXVkaW8=", **options})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("selection", [
    {}, {"fields": None}, {"fields": "Back"}, {"fields": []}, {"fields": ["Back"]},
    {"fields": ["Back", "Back"]}, {"fields": {"Back": 1}}, {"fields": 7},
    {"fields": False}, {"fields": [7]}, {"fields": [["Back"]]},
])
@pytest.mark.parametrize("data", ["YXVkaW8=", "AA"])
@pytest.mark.parametrize("action", ["updateNoteFields", "canAddNoteWithErrorDetail"])
def test_nested_media_field_selection(pair, selection, data, action):
    media = {"filename": "field-selection.mp3", "data": data, **selection}
    if action == "updateNoteFields":
        note = {"id": pair[0].find_notes("")[0], "fields": {"Back": "updated"}, "audio": media}
    else:
        note = {"deckName": "Default", "modelName": "Basic",
                "fields": {"Front": "field selection probe", "Back": "back"}, "audio": media}
    compare(pair, action, {"note": note})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("selection", [{}, {"fields": None}])
@pytest.mark.parametrize("action", ["updateNoteFields", "canAddNoteWithErrorDetail"])
def test_nested_media_error_keeps_prefix_and_stops_suffix(pair, selection, action):
    media = [
        {"filename": "prefix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
        {"filename": "failed.mp3", "data": "AA", **selection},
        {"filename": "suffix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
    ]
    if action == "updateNoteFields":
        note = {"id": pair[0].find_notes("")[0], "fields": {"Back": "updated"}, "audio": media}
    else:
        note = {"deckName": "Default", "modelName": "Basic",
                "fields": {"Front": "partial media probe", "Back": "back"}, "audio": media}
    compare(pair, action, {"note": note})
    assert_note_and_media_state(pair)
    assert media_state(pair[0]) == {"prefix.mp3": b"audio"}


@pytest.mark.parametrize("selection", [{}, {"fields": None}, {"fields": ["Back"]}, {"fields": {"Back": 1}}])
def test_nested_media_storage_errors(pair, monkeypatch, selection):
    def fail_write(*args, **kwargs):
        raise OSError("<storage>&failure")

    for collection in pair[:2]:
        monkeypatch.setattr(collection.media, "write_data", fail_write)
    media = {"filename": "failed-write.mp3", "data": "YXVkaW8=", **selection}
    note = {"id": pair[0].find_notes("")[0], "fields": {"Back": "updated"}, "picture": media}
    compare(pair, "updateNoteFields", {"note": note})
    assert_note_and_media_state(pair)
    assert media_state(pair[0]) == {}


@pytest.mark.parametrize("media", [
    None, False, 0, "", "malformed", [], [None], {}, {"fields": ["Back"]},
    {"filename": None, "data": "YXVkaW8=", "fields": ["Back"]},
    {"filename": 7, "data": "YXVkaW8=", "fields": ["Back"]},
    *({"filename": "raw.mp3", "data": value, "fields": ["Back"]}
      for value in (None, 0, False, [], [1], {}, {"key": "value"})),
    {"filename": "raw.mp3", "url": 7, "fields": ["Back"]},
    *({"filename": "raw.mp3", "data": "YXVkaW8=", "skipHash": value, "fields": ["Back"]}
      for value in (0, False, [], {"key": "value"})),
])
@pytest.mark.parametrize("action", ["updateNoteFields", "canAddNoteWithErrorDetail"])
def test_nested_raw_media_values(pair, media, action):
    if action == "updateNoteFields":
        note = {"id": pair[0].find_notes("")[0], "fields": {"Back": "updated"}, "audio": media}
    else:
        note = {"deckName": "Default", "modelName": "Basic",
                "fields": {"Front": "raw media probe", "Back": "back"}, "audio": media}
    compare(pair, action, {"note": note})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("malformed", [False, "malformed", ["malformed"]])
def test_malformed_attachment_keeps_earlier_media(pair, malformed):
    media = [
        {"filename": "prefix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
        malformed,
        {"filename": "suffix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
    ]
    note = {"id": pair[0].find_notes("")[0], "fields": {"Back": "updated"}, "picture": media}
    compare(pair, "updateNoteFields", {"note": note})
    assert_note_and_media_state(pair)
    assert media_state(pair[0]) == {"prefix.mp3": b"audio"}


@pytest.mark.parametrize("params", [
    {"filename": None, "data": "YXVkaW8="}, {"filename": 7, "data": "YXVkaW8="},
    *({"filename": "raw.mp3", "data": value}
      for value in (None, 0, False, [], [1], {}, {"key": "value"})),
    {"filename": "raw.mp3", "url": 7},
    *({"filename": "raw.mp3", "data": "YXVkaW8=", "skipHash": value}
      for value in (0, False, [], {"key": "value"})),
])
def test_raw_store_media_values(pair, params):
    compare(pair, "storeMediaFile", params)
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("filename", [None, 7])
@pytest.mark.parametrize("delete", [False, True])
@pytest.mark.parametrize("skip", [False, True])
@pytest.mark.parametrize("action", ["storeMediaFile", "updateNoteFields"])
def test_media_filename_validation_order(pair, filename, delete, skip, action):
    media = {"filename": filename, "data": "YXVkaW8=", "deleteExisting": delete}
    if skip:
        media["skipHash"] = "a5ca0b5894324f8bb54bb9fffad29d1e"
    params = media if action == "storeMediaFile" else {"note": {
        "id": pair[0].find_notes("")[0], "fields": {"Back": "updated"},
        "audio": {**media, "fields": ["Back"]},
    }}
    compare(pair, action, params)
    assert_note_and_media_state(pair)
    assert media_state(pair[0]) == {}


@pytest.mark.parametrize("change", [
    {"fields": {"Front": "changed", "Unknown": "ignored"}},
    {"fields": {}, "tags": ["new", "root::child"]},
    {"fields": {"Back": "changed"}, "tags": []},
])
def test_update_note_side_effects(pair, change):
    nid = pair[0].find_notes("")[0]
    compare(pair, "updateNote", {"note": {"id": nid, **change}})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("media", [
    {"filename": "attachment.mp3", "data": "YXVkaW8=", "fields": ["Back", "Unknown"]},
    {"filename": "attachment.mp3", "data": "YXVkaW8="},
    {"filename": "attachment.mp3", "data": "AA", "fields": ["Back"]},
    [None, {"filename": "attachment.mp3", "data": "YXVkaW8=", "fields": ["Back"]}],
])
def test_update_note_fields_with_media(pair, media):
    nid = pair[0].find_notes("")[0]
    compare(pair, "updateNoteFields", {"note": {"id": nid, "fields": {"Back": "updated"}, "audio": media}})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("action", ["canAddNote", "canAddNotes", "canAddNoteWithErrorDetail", "canAddNotesWithErrorDetail"])
@pytest.mark.parametrize("front,media_field", [
    ("new probe", "Back"), ("", "Back"), ("alpha", "Back"), ("", "Front"),
])
def test_note_probe_media_side_effects(pair, action, front, media_field):
    note = {
        "deckName": "Default", "modelName": "Basic", "fields": {"Front": front, "Back": ""},
        "audio": {"filename": "probe.mp3", "data": "YXVkaW8=", "fields": [media_field]},
    }
    params = {"notes": [note]} if action in {"canAddNotes", "canAddNotesWithErrorDetail"} else {"note": note}
    compare(pair, action, params)
    assert_note_and_media_state(pair)


def test_add_notes_rollback_and_media_side_effects(pair):
    note = {
        "deckName": "Default", "modelName": "Basic", "fields": {"Front": "rollback probe", "Back": ""},
        "audio": {"filename": "rollback.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
    }
    compare(pair, "addNotes", {"notes": [note, {**note, "modelName": "Missing model"}]})
    assert_note_and_media_state(pair)


def test_delete_notes_duplicate_and_missing_ids(pair):
    nid = pair[0].find_notes("")[0]
    compare(pair, "deleteNotes", {"notes": [nid, nid, 9999999999999]})
    assert_note_and_media_state(pair)


def mutation_state(collection):
    """Compare cache and persisted state, excluding time metadata and allocated IDs.

    New fields/templates and cards allocate IDs independently. Compare their
    ordered definitions and match cards by note/template. Undo and Qt effects
    need the live harness.
    """
    models = []
    for model in collection.models.all():
        model = copy.deepcopy(model)
        model.pop("mod", None)
        for member in model["flds"] + model["tmpls"]:
            member.pop("id", None)
        models.append(model)
    collection.models._clear_cache()
    persisted_models = []
    for model in collection.models.all():
        model = copy.deepcopy(model)
        model.pop("mod", None)
        for member in model["flds"] + model["tmpls"]:
            member.pop("id", None)
        persisted_models.append(model)
    return {
        "models": sorted(models, key=lambda model: model["id"]),
        "persisted_models": sorted(persisted_models, key=lambda model: model["id"]),
        "notes": collection.db.all("select id, mid, flds, tags from notes order by id"),
        "cards": collection.db.all(
            "select nid, did, ord, type, queue, due, ivl, factor, reps, lapses, "
            "left, odue, odid, flags, data from cards order by nid, ord"
        ),
        "reviews": collection.db.all(
            "select cid, ease, ivl, lastIvl, factor, time, type from revlog order by id"
        ),
    }


def assert_mutation_state(pair):
    actual, expected = mutation_state(pair[0]), mutation_state(pair[1])
    assert actual == expected, first_difference(actual, expected, "collection")


@pytest.mark.parametrize("action,params", [
    ("updateModelStyling", {"model": {"name": "Basic", "css": ".card {color: red;}"}}),
    ("updateModelTemplates", {"model": {"name": "Basic", "templates": {
        "Card 1": {"Front": "{{Front}}!", "Back": "{{Back}}!"}}}}),
    ("updateModelTemplates", {"model": {"name": "Basic", "templates": {
        "Card 1": {"Front": "", "Back": ""}, "Unknown": {"Front": "ignored"}}}}),
    ("modelTemplateRename", {"oldTemplateName": "Card 1", "newTemplateName": "Renamed"}),
    ("modelTemplateReposition", {"templateName": "Card 1", "index": 0}),
    ("modelTemplateAdd", {"template": {"Name": "Reverse", "Front": "{{Back}}", "Back": "{{Front}}"}}),
    ("modelTemplateAdd", {"template": {"Name": "Card 1", "Front": "{{Back}}", "Back": "{{Front}}"}}),
    ("modelFieldRename", {"oldFieldName": "Front", "newFieldName": "Question"}),
    ("modelFieldReposition", {"fieldName": "Back", "index": 0}),
    ("modelFieldAdd", {"fieldName": "Extra"}),
    ("modelFieldAdd", {"fieldName": "Extra", "index": 0}),
    ("modelFieldAdd", {"fieldName": "Back", "index": 0}),
    ("modelFieldSetFont", {"fieldName": "Front", "font": "Arial"}),
    ("modelFieldSetFontSize", {"fieldName": "Front", "fontSize": 24}),
    ("modelFieldSetDescription", {"fieldName": "Front", "description": "Question text"}),
    ("findAndReplaceInModels", {"findText": "Front", "replaceText": "Front", "css": False}),
    ("modelFieldRemove", {"fieldName": "missing"}),
    ("modelTemplateRemove", {"templateName": "missing"}),
])
def test_model_mutations(pair, action, params):
    if "model" not in params:
        params = {"modelName": "Basic", **params}
    compare(pair, action, params)
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["modelFieldRemove", "modelTemplateRemove"])
def test_model_remove_added_item(pair, action):
    if action == "modelFieldRemove":
        compare(pair, "modelFieldAdd", {"modelName": "Basic", "fieldName": "Extra"})
        params = {"fieldName": "Extra"}
    else:
        compare(pair, "modelTemplateAdd", {"modelName": "Basic", "template": {
            "Name": "Reverse", "Front": "{{Back}}", "Back": "{{Front}}"}})
        params = {"templateName": "Reverse"}
    compare(pair, action, {"modelName": "Basic", **params})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action,extra", [
    ("setEaseFactors", {"easeFactors": [2100, 2700, 2900]}),
    ("setEaseFactors", {"easeFactors": [2100]}),
    ("setDueDate", {"days": "5"}),
    ("setDueDate", {"days": "0!"}),
    ("setDueDate", {"days": "invalid"}),
    ("forgetCards", {}),
    ("relearnCards", {}),
    ("suspend", {}),
    ("unsuspend", {}),
])
@pytest.mark.parametrize("review_cards", [False, True])
def test_scheduler_mutations(pair, action, extra, review_cards):
    cards = list(pair[0].find_cards(""))
    if review_cards:
        for collection in pair[:2]:
            collection.db.execute(
                "update cards set type=2, queue=2, due=?, ivl=10, factor=2500, reps=3",
                collection.sched.today,
            )
    compare(pair, action, {"cards": cards, **extra})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["getEaseFactors", "cardsToNotes"])
@pytest.mark.parametrize("case", [
    "none", "false", "true", "number", "fraction", "empty-string", "zero-string", "string",
    "empty-dict", "dict", "empty", "null-id", "zero-id", "false-id", "true-id",
    "float-id", "fraction-id", "string-id", "nested-id", "object-id", "missing",
    "negative", "overflow", "underflow", "reverse", "duplicate", "bad-suffix", "bad-prefix",
])
def test_remaining_card_reads_raw_inputs(pair, action, case):
    ids = list(pair[0].find_cards(""))
    cid = ids[0]
    values = {
        "none": None, "false": False, "true": True, "number": cid, "fraction": 1.5,
        "empty-string": "", "zero-string": "0", "string": str(cid), "empty-dict": {},
        "dict": {str(cid): True}, "empty": [], "null-id": [None], "zero-id": [0],
        "false-id": [False], "true-id": [True], "float-id": [float(cid)],
        "fraction-id": [cid + 0.5], "string-id": [str(cid)], "nested-id": [[]],
        "object-id": [{}], "missing": [999999], "negative": [-1], "overflow": [2**63],
        "underflow": [-2**63 - 1], "reverse": list(reversed(ids)), "duplicate": [cid, cid],
        "bad-suffix": [cid, None, ids[1]], "bad-prefix": [None, cid],
    }
    compare(pair, action, {"cards": values[case]})
    assert_mutation_state(pair)


@pytest.mark.parametrize("complete", [None, False, True, 0, 1, -1, 1.5, "", "false", "true", [], [False], {}, {"x": False}])
@pytest.mark.parametrize("layout", ["empty", "new", "review", "missing", "mixed", "raw"])
def test_intervals_raw_complete_flag(pair, complete, layout):
    ids = list(pair[0].find_cards(""))
    for collection in pair[:2]:
        card = collection.get_card(ids[0])
        card.type = card.queue = 2
        card.ivl = 5
        card.due = collection.sched.today
        collection.update_card(card)
        for offset, interval in enumerate([-60, 1, 5]):
            collection.db.execute(
                "insert into revlog values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                1720000000000 + offset, ids[0], -1, 3, interval, 1, 2500, 100, 1,
            )
    cards = {"empty": [], "new": [ids[1]], "review": [ids[0]], "missing": [999999],
             "mixed": [ids[1], ids[0], 999999], "raw": [str(ids[0]), float(ids[0])]}[layout]
    compare(pair, "getIntervals", {"cards": cards, "complete": complete})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["suspend", "unsuspend", "areSuspended"])
@pytest.mark.parametrize("case", [
    "none", "false", "integer", "empty-string", "string", "empty-dict", "dict",
    "empty", "null-id", "zero-id", "false-id", "true-id", "float-id", "string-id",
    "nested-id", "object-id", "missing", "duplicate", "bad-suffix", "bad-prefix",
    "overflow-id", "underflow-id",
])
def test_suspension_raw_inputs(pair, action, case):
    ids = list(pair[0].find_cards(""))
    cid = ids[0]
    values = {
        "none": None, "false": False, "integer": cid,
        "empty-string": "", "string": str(cid), "empty-dict": {},
        "dict": {str(cid): True}, "empty": [], "null-id": [None], "zero-id": [0],
        "false-id": [False], "true-id": [True], "float-id": [float(cid)],
        "string-id": [str(cid)], "nested-id": [[]], "object-id": [{}],
        "missing": [999999], "duplicate": [cid, cid],
        "bad-suffix": [cid, None, ids[1]], "bad-prefix": [None, cid],
    }
    values.update({"overflow-id": [2**63], "underflow-id": [-2**63 - 1]})
    compare(pair, action, {"cards": values[case]})
    assert_mutation_state(pair)


@pytest.mark.parametrize("value", [None, False, True, 0, 1, 1.5, "", "1", [], {}])
def test_suspended_raw_input(pair, value):
    compare(pair, "suspended", {"card": value})


@pytest.mark.parametrize("flag", [None, False, True, 0, 1, 1.5, "", "false", [], {}, [1]])
@pytest.mark.parametrize("suspended", [False, True])
def test_suspension_raw_flag(pair, flag, suspended):
    cards = list(pair[0].find_cards(""))
    if suspended:
        for collection in pair[:2]:
            collection.sched.suspend_cards(cards)
    compare(pair, "suspend", {"cards": cards, "suspend": flag})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["suspend", "unsuspend"])
@pytest.mark.parametrize("skipped", [None, [], {}, "bad", 999999])
def test_suspension_skips_raw_validation_after_removal(pair, action, skipped):
    cards = list(pair[0].find_cards(""))
    if action == "suspend":
        for collection in pair[:2]:
            collection.sched.suspend_cards([cards[0]])
    compare(pair, action, {"cards": [cards[0], skipped, cards[1]]})
    assert_mutation_state(pair)


def assert_answer_state(pair):
    actual, expected = mutation_state(pair[0]), mutation_state(pair[1])
    for actual_card, expected_card in zip(actual["cards"], expected["cards"]):
        # Intraday due times can use Rust's wall clock independently of the
        # supplied answer timestamp. The shim runs second: permit one forward
        # second of rollover, while comparing intervals and all other state.
        if actual_card[4] == expected_card[4] and actual_card[4] in (1, 4):
            if 0 <= actual_card[5] - expected_card[5] <= 1:
                actual_card[5] = expected_card[5]
    assert actual == expected, first_difference(actual, expected, "collection")


@pytest.fixture()
def answer_clock(monkeypatch):
    from anki.cards import Card
    from anki.scheduler import v3

    answered_at = v3.int_time()
    monkeypatch.setattr(v3, "int_time", lambda scale=1: answered_at * scale)

    def time_taken(card, capped=True):
        assert card.timer_started is not None
        return 1234

    # Both calls must start their timer. Fix the answer timestamp and elapsed
    # time so sequential calls have identical external clock inputs.
    monkeypatch.setattr(Card, "time_taken", time_taken)


@pytest.mark.parametrize("answers", [None, False, True, 1, "", "x", {}, {"cardId": 1}, [], [None], [False], [1], ["x"], [[]], [{}]])
@pytest.mark.usefixtures("answer_clock")
def test_answer_raw_containers(pair, answers):
    compare(pair, "answerCards", {"answers": answers})
    assert_answer_state(pair)


@pytest.mark.parametrize("field", ["cardId", "ease"])
@pytest.mark.parametrize("value", [None, False, True, 0, -1, 1.5, "", "3", [], {}])
@pytest.mark.parametrize("prefix", [False, True])
@pytest.mark.usefixtures("answer_clock")
def test_answer_raw_entry_values(pair, field, value, prefix):
    cards = list(pair[0].find_cards(""))
    answer = {"cardId": cards[1], "ease": 3, field: value}
    answers = ([{"cardId": cards[0], "ease": 3}] if prefix else []) + [answer]
    compare(pair, "answerCards", {"answers": answers})
    assert_answer_state(pair)
    if prefix:
        for collection in pair[:2]:
            assert collection.db.scalar("select count(*) from revlog where cid=?", cards[0]) == 1


@pytest.mark.parametrize("malformed", [None, False, 1, "x", [], {}, {"cardId": 1}])
@pytest.mark.parametrize("first_ease", [3, "3", 0])
@pytest.mark.usefixtures("answer_clock")
def test_answer_raw_suffix_keeps_prefix(pair, malformed, first_ease):
    cards = list(pair[0].find_cards(""))
    answers = [{"cardId": cards[0], "ease": first_ease}, malformed, {"cardId": cards[1], "ease": 3}]
    compare(pair, "answerCards", {"answers": answers})
    assert_answer_state(pair)


@pytest.mark.parametrize("kind", ["string", "float", "duplicate"])
@pytest.mark.usefixtures("answer_clock")
def test_answer_raw_existing_ids(pair, kind):
    cid = list(pair[0].find_cards(""))[0]
    value = str(cid) if kind == "string" else float(cid) if kind == "float" else cid
    answers = [{"cardId": value, "ease": 3}] * (2 if kind == "duplicate" else 1)
    compare(pair, "answerCards", {"answers": answers})
    assert_answer_state(pair)


@pytest.mark.parametrize("ease", [None, [], {}, "3", 0, 99])
@pytest.mark.usefixtures("answer_clock")
def test_answer_raw_missing_card_defers_ease(pair, ease):
    cid = list(pair[0].find_cards(""))[0]
    assert compare(pair, "answerCards", {"answers": [
        {"cardId": 999999, "ease": ease}, {"cardId": cid, "ease": 3},
    ]}) == {"result": [False, True], "error": None}
    assert_answer_state(pair)


@pytest.mark.usefixtures("answer_clock")
def test_answer_raw_saved_prefix_notifications(pair):
    from tsunagi.adapters.anki.compat import answer_cards_raw

    cid = list(pair[0].find_cards(""))[0]
    answers = [{"cardId": cid, "ease": 3}, None]
    expected = pair[2].handler({"action": "answerCards", "version": 6, "params": {"answers": answers}})
    result = answer_cards_raw.__wrapped__(pair[0], answers)
    assert hasattr(result, "changes"), result
    assert result.value == (None, expected["error"])
    assert result.changes.card
    assert_answer_state(pair)


@pytest.mark.parametrize("action", ["suspend", "unsuspend"])
@pytest.mark.parametrize("state", ["new", "review", "learning", "relearning", "buried", "suspended"])
def test_suspension_raw_state_undo(pair, action, state):
    cards = list(pair[0].find_cards(""))
    states = {"new": (0, 0), "review": (2, 2), "learning": (1, 1),
              "relearning": (3, 1), "buried": (2, -2), "suspended": (2, -1)}
    for collection in pair[:2]:
        collection.db.execute("update cards set type=?, queue=?", *states[state])
        collection.update_card(collection.get_card(cards[0]), skip_undo_entry=True)
    compare(pair, action, {"cards": cards})
    assert_mutation_state(pair)
    statuses = [c.undo_status() for c in pair[:2]]
    assert (statuses[0].undo, statuses[0].redo) == (statuses[1].undo, statuses[1].redo)
    if statuses[0].undo:
        for collection in pair[:2]:
            collection.undo()
        assert_mutation_state(pair)
        for collection in pair[:2]:
            collection.redo()
        assert_mutation_state(pair)


@pytest.mark.parametrize("fsrs", [False, True])
@pytest.mark.parametrize("filtered", [None, False, True])
@pytest.mark.parametrize("ease", [1, 3, 4])
@pytest.mark.usefixtures("answer_clock")
def test_answer_raw_filtered_memory_undo(pair, fsrs, filtered, ease):
    cards = list(pair[0].find_cards(""))
    for collection in pair[:2]:
        collection.set_config("fsrs", fsrs)
        collection.db.execute(
            "update cards set type=2, queue=2, due=?, ivl=10, factor=2500, reps=8, lapses=2, data=?",
            collection.sched.today, json.dumps({"s": 12.0, "d": 5.0}),
        )
        if filtered is not None:
            did = collection.decks.new_filtered("Parity filtered answer")
            deck = collection.decks.get(did)
            deck["resched"] = filtered
            collection.decks.save(deck)
            collection.db.execute("update decks set id=900000 where id=?", did)
            collection.sched.rebuild_filtered_deck(900000)
            assert collection.db.scalar("select count(*) from cards where odid != 0") == len(cards)
        collection.update_card(collection.get_card(cards[0]), skip_undo_entry=True)
    reply = compare(pair, "answerCards", {"answers": [{"cardId": cards[0], "ease": ease}, None]})
    assert reply == {"result": None, "error": "'NoneType' object is not subscriptable"}
    assert_answer_state(pair)
    for collection in pair[:2]:
        collection.undo()
    assert_answer_state(pair)
    for collection in pair[:2]:
        collection.redo()
    assert_answer_state(pair)


@pytest.mark.parametrize("action", ["forgetCards", "relearnCards", "setDueDate"])
@pytest.mark.parametrize("case", [
    "none", "false", "true", "integer", "empty-string", "string", "empty-dict",
    "dict", "empty", "null-id", "false-id", "true-id", "float-id", "string-id",
    "nested-id", "object-id", "missing", "duplicate", "bad-suffix", "bad-prefix",
])
def test_reschedule_raw_card_inputs(pair, action, case):
    ids = list(pair[0].find_cards(""))
    cid = ids[0]
    values = {
        "none": None, "false": False, "true": True, "integer": cid,
        "empty-string": "", "string": str(cid), "empty-dict": {},
        "dict": {str(cid): True}, "empty": [], "null-id": [None],
        "false-id": [False], "true-id": [True], "float-id": [float(cid)],
        "string-id": [str(cid)], "nested-id": [[]], "object-id": [{}],
        "missing": [999999], "duplicate": [cid, cid],
        "bad-suffix": [cid, None, ids[1]], "bad-prefix": [None, cid],
    }
    params = {"cards": values[case]}
    if action == "setDueDate":
        params["days"] = "5"
    compare(pair, action, params)
    assert_mutation_state(pair)


@pytest.mark.parametrize("days", [None, False, True, 0, 5, 1.5, [], {}, "", "bad", "-1", "5!", "2-2"])
@pytest.mark.parametrize("layout", ["present", "empty", "invalid"])
def test_reschedule_raw_days(pair, days, layout):
    cards = list(pair[0].find_cards("")) if layout == "present" else ([] if layout == "empty" else [None])
    compare(pair, "setDueDate", {"cards": cards, "days": days})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["forgetCards", "relearnCards", "setDueDate"])
@pytest.mark.parametrize("state", ["learning", "day-learning", "relearning", "suspended", "buried", "filtered"])
def test_reschedule_existing_states(pair, action, state):
    cards = list(pair[0].find_cards(""))
    for collection in pair[:2]:
        collection.db.execute(
            "update cards set type=2, queue=2, due=?, ivl=10, factor=2500, reps=8, lapses=2",
            collection.sched.today,
        )
        if state == "learning":
            collection.db.execute("update cards set type=1, queue=1, due=1700000000, left=2002")
        elif state == "day-learning":
            collection.db.execute("update cards set type=1, queue=3, left=1001")
        elif state == "relearning":
            collection.db.execute("update cards set type=3, queue=1, due=1700000000, left=1001")
        elif state in ("suspended", "buried"):
            collection.db.execute("update cards set queue=?", -1 if state == "suspended" else -2)
        else:
            # Use a fixed unused deck ID to compare actual filtered-deck metadata.
            deck = collection.decks.new_filtered("Parity filtered")
            collection.db.execute("update decks set id=900000 where id=?", deck)
            collection.sched.rebuild_filtered_deck(900000)
            assert collection.db.scalar("select count(*) from cards where odid != 0") == len(cards)
    compare(pair, action, {"cards": cards, **({"days": "5"} if action == "setDueDate" else {})})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["forgetCards", "relearnCards", "setDueDate"])
@pytest.mark.parametrize("fsrs", [False, True])
@pytest.mark.parametrize("filtered", [None, False, True])
def test_reschedule_memory_and_undo(pair, action, fsrs, filtered):
    cards = list(pair[0].find_cards(""))
    for collection in pair[:2]:
        collection.set_config("fsrs", fsrs)
        collection.db.execute(
            "update cards set type=2, queue=2, due=?, ivl=10, factor=2500, reps=8, lapses=2, data=?",
            collection.sched.today,
            json.dumps({"s": 12.0, "d": 5.0, "pos": 17}),
        )
        if filtered is not None:
            did = collection.decks.new_filtered("Parity filtered undo")
            deck = collection.decks.get(did)
            deck["resched"] = filtered
            collection.decks.save(deck)
            collection.db.execute("update decks set id=900000 where id=?", did)
            collection.sched.rebuild_filtered_deck(900000)
            assert collection.db.scalar("select count(*) from cards where odid != 0") == len(cards)
        # Establish observable undo history before the action. Anki's raw SQL
        # relearning clears it; scheduler operations add undoable steps.
        collection.update_card(collection.get_card(cards[0]), skip_undo_entry=True)
        collection.sched.suspend_cards([cards[-1]])
    before = [c.undo_status() for c in pair[:2]]
    assert (before[0].undo, before[0].redo) == (before[1].undo, before[1].redo)
    compare(pair, action, {"cards": cards, **({"days": "5"} if action == "setDueDate" else {})})
    assert_mutation_state(pair)
    after = [c.undo_status() for c in pair[:2]]
    assert (after[0].undo, after[0].redo) == (after[1].undo, after[1].redo)
    if action == "relearnCards":
        assert not after[0].undo and not after[0].redo
        assert after[0].last_step == after[1].last_step == 0
        return
    assert after[0].last_step - before[0].last_step == after[1].last_step - before[1].last_step
    for collection in pair[:2]:
        collection.undo()
    assert_mutation_state(pair)
    for collection in pair[:2]:
        collection.redo()
    assert_mutation_state(pair)


@pytest.mark.parametrize("layout", ["present", "missing-first", "missing-only", "empty"])
@pytest.mark.parametrize("factors", [
    None, False, True, 0, 1.5, "", "2700", {}, {"0": 2700}, [], [2700],
    [2700, None, 2800], [2700, False, 2800], [2700, 2500.5, 2800],
    [2700, "2500", 2800], [2700, [], 2800], [2700, {}, 2800],
    [2700, -1, 2800], [2700, 2**32, 2800],
])
def test_set_ease_factor_values_and_partial_writes(pair, layout, factors):
    cards = list(pair[0].find_cards(""))
    missing = 9999999999999
    ids = {"present": cards, "missing-first": [missing, *cards[:2]],
           "missing-only": [missing], "empty": []}[layout]
    compare(pair, "setEaseFactors", {"cards": ids, "easeFactors": factors})
    assert_mutation_state(pair)


@pytest.mark.parametrize("case", [
    "null", "false", "scalar", "text", "empty-map", "map", "string-id",
    "float-id", "boolean-id", "null-id", "nested-id",
])
def test_set_ease_card_values_and_partial_writes(pair, case):
    cards = list(pair[0].find_cards(""))
    ids = {
        "null": None, "false": False, "scalar": cards[0], "text": "invalid",
        "empty-map": {}, "map": {str(cards[0]): True},
        "string-id": [cards[0], str(cards[1]), cards[2]],
        "float-id": [cards[0], float(cards[1]), cards[2]],
        "boolean-id": [cards[0], True, cards[2]],
        "null-id": [cards[0], None, cards[2]],
        "nested-id": [cards[0], [], cards[2]],
    }[case]
    compare(pair, "setEaseFactors", {"cards": ids, "easeFactors": [2700, 2600, 2800]})
    assert_mutation_state(pair)


@pytest.mark.parametrize("case", [
    "native-success", "ignored-suffix", "late-failure", "empty", "missing-only", "early-failure",
])
def test_set_ease_undo_matches_upstream(pair, case):
    cards = list(pair[0].find_cards(""))
    seed_id = cards[0]
    factors = [2700, 2800, 2900]
    if case == "ignored-suffix":
        cards = cards[:2]
        factors[-1] = "unused"
    elif case == "late-failure":
        factors[1] = "invalid"
    elif case == "empty":
        cards = []
    elif case == "missing-only":
        cards = [9999999999999]
    elif case == "early-failure":
        factors[0] = "invalid"
    for collection in pair[:2]:
        card = collection.get_card(seed_id)
        card.factor = 2500
        collection.update_card(card)
        assert collection.undo_status().undo
    before = [collection.undo_status() for collection in pair[:2]]
    compare(pair, "setEaseFactors", {"cards": cards, "easeFactors": factors})
    assert_mutation_state(pair)
    if case in ("empty", "missing-only", "early-failure"):
        for collection, status in zip(pair[:2], before):
            assert collection.undo_status() == status
    else:
        assert pair[0].undo_status() == pair[1].undo_status()
        assert not pair[1].undo_status().undo


@pytest.mark.parametrize("action", ["updateNoteTags", "updateNote"])
@pytest.mark.parametrize("tags", [
    None, False, 1, {}, [], "", "one two", " spaced  tags ", "日本語",
    ["one", "two"], ["Case", "case", "Case"], ["root::child", "other"],
    ["one two", "three"], ["*", "a?b"], ["valid", None], ["valid", 1], [[], {}],
])
def test_replace_note_tags_values(pair, action, tags):
    nid = pair[0].find_notes("")[0]
    params = {"note": nid, "tags": tags} if action == "updateNoteTags" else {
        "note": {"id": nid, "tags": tags},
    }
    compare(pair, action, params)
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["getNoteTags", "updateNoteTags"])
@pytest.mark.parametrize("case", [
    "null", "false", "true", "zero", "missing", "string-id", "float-id",
    "text", "empty-list", "list", "empty-map", "map",
])
def test_note_tag_id_values(pair, action, case):
    nid = pair[0].find_notes("")[0]
    note = {"null": None, "false": False, "true": True, "zero": 0,
            "missing": 9999999999999, "string-id": str(nid), "float-id": float(nid),
            "text": "invalid", "empty-list": [], "list": [nid], "empty-map": {},
            "map": {"id": nid}}[case]
    params = {"note": note}
    if action == "updateNoteTags":
        params["tags"] = ["replacement"]
    compare(pair, action, params)
    assert_mutation_state(pair)


@pytest.mark.parametrize("note", [None, "invalid", [], 9999999999999])
def test_note_tags_validation_precedes_lookup(pair, note):
    before = mutation_state(pair[0])
    compare(pair, "updateNoteTags", {"note": note, "tags": ["valid", None]})
    assert_mutation_state(pair)
    assert mutation_state(pair[0]) == before


@pytest.mark.parametrize("action", ["updateNoteTags", "updateNote"])
@pytest.mark.parametrize("steps", [1, 2, 3])
def test_note_tag_replacement_undo_redo(pair, action, steps):
    nid = pair[0].find_notes("")[0]
    params = {"note": nid, "tags": ["one", "two"]} if action == "updateNoteTags" else {
        "note": {"id": nid, "tags": ["one", "two"]},
    }
    compare(pair, action, params)
    assert_mutation_state(pair)
    for _ in range(steps):
        for collection in pair[:2]:
            collection.undo()
        assert_mutation_state(pair)
    for _ in range(steps):
        for collection in pair[:2]:
            collection.redo()
        assert_mutation_state(pair)


@pytest.mark.parametrize("tags", [None, False, 1, [], "one two", ["valid", None], ["one", "two"]])
def test_update_note_fields_precede_tag_validation(pair, tags):
    nid = pair[0].find_notes("")[0]
    compare(pair, "updateNote", {"note": {
        "id": nid, "fields": {"Back": "saved before tags"}, "tags": tags,
    }})
    assert_mutation_state(pair)
    for collection in pair[:2]:
        assert collection.get_note(nid)["Back"] == "saved before tags"


@pytest.mark.parametrize("action", ["addTags", "removeTags"])
@pytest.mark.parametrize("case", [
    "null", "false", "scalar", "string", "text", "empty-list", "empty-map", "map",
    "string-list", "float-list", "boolean-list", "null-list", "nested-list", "mixed", "missing",
])
def test_bulk_tag_note_values(pair, action, case):
    notes = list(pair[0].find_notes(""))
    value = {
        "null": None, "false": False, "scalar": notes[0], "string": str(notes[0]),
        "text": "invalid", "empty-list": [], "empty-map": {}, "map": {str(notes[0]): True},
        "string-list": [str(notes[0])], "float-list": [float(notes[0])],
        "boolean-list": [True, False], "null-list": [None], "nested-list": [[]],
        "mixed": [notes[0], "invalid", notes[-1]], "missing": [9999999999999],
    }[case]
    before = mutation_state(pair[0])
    compare(pair, action, {"notes": value, "tags": "root::child fresh"})
    assert_mutation_state(pair)
    if case == "mixed":
        assert mutation_state(pair[0]) == before


@pytest.mark.parametrize("action", ["addTags", "removeTags"])
@pytest.mark.parametrize("layout", ["present", "empty", "missing"])
@pytest.mark.parametrize("tags", [None, False, 123, 1.5, [], ["tag"], {}, "", "one two", " a\tb ", "日本語", "root::*"])
def test_bulk_tag_value_types(pair, action, layout, tags):
    notes = list(pair[0].find_notes(""))
    ids = {"present": notes, "empty": [], "missing": [9999999999999]}[layout]
    compare(pair, action, {"notes": ids, "tags": tags})
    assert_mutation_state(pair)


@pytest.mark.parametrize("add", [None, False, True, 0, 1, "", "false", "0", [], [1], {}, {"enabled": False}])
def test_bulk_tag_add_flag_truthiness(pair, add):
    compare(pair, "addTags", {"notes": list(pair[0].find_notes("")),
                             "tags": "root::child fresh", "add": add})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["addTags", "removeTags"])
def test_bulk_tag_undo_redo(pair, action):
    compare(pair, action, {"notes": list(pair[0].find_notes("")), "tags": "root::child fresh"})
    assert_mutation_state(pair)
    for collection in pair[:2]:
        collection.undo()
    assert_mutation_state(pair)
    for collection in pair[:2]:
        collection.redo()
    assert_mutation_state(pair)


@pytest.fixture
def replace_reference_ui(pair, monkeypatch):
    from types import SimpleNamespace

    window = pair[2].window()
    monkeypatch.setattr(window, "progress", SimpleNamespace(start=lambda: None, finish=lambda: None), raising=False)
    monkeypatch.setattr(window, "requireReset", lambda: None, raising=False)
    monkeypatch.setattr(window, "reset", lambda: None, raising=False)


@pytest.mark.parametrize("action", ["replaceTags", "replaceTagsInAllNotes"])
@pytest.mark.parametrize("old,new", [
    (None, "new"), (False, "new"), (123, "new"), ([], "new"), ({}, "new"),
    ("", "new"), ("root", "new"), ("root::*", "new"), ("ROOT::CHILD", "new"),
    ("root::child", None), ("root::child", False), ("root::child", 123),
    ("root::child", []), ("root::child", {}), ("root::child", "two tags"),
    ("missing", None), ("missing", []), ("root::child", ""),
])
def test_replace_tags_raw_values(pair, replace_reference_ui, action, old, new):
    params = {"tag_to_replace": old, "replace_with_tag": new}
    if action == "replaceTags":
        params["notes"] = list(pair[0].find_notes(""))
    compare(pair, action, params)
    assert_mutation_state(pair)


@pytest.mark.parametrize("case", [
    "null", "false", "scalar", "string", "empty-map", "map", "string-list",
    "float-list", "boolean-list", "null-list", "mixed", "missing",
])
def test_replace_tags_raw_note_ids(pair, replace_reference_ui, case):
    ids = list(pair[0].find_notes(""))
    notes = {"null": None, "false": False, "scalar": ids[0], "string": str(ids[0]),
             "empty-map": {}, "map": {str(ids[0]): True}, "string-list": [str(ids[0])],
             "float-list": [float(ids[0])], "boolean-list": [True, False],
             "null-list": [None], "mixed": [ids[0], "invalid", ids[-1]],
             "missing": [9999999999999, ids[0]]}[case]
    compare(pair, "replaceTags", {"notes": notes, "tag_to_replace": "root::child",
                                  "replace_with_tag": "renamed"})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["replaceTags", "replaceTagsInAllNotes"])
@pytest.mark.parametrize("old", ["root::child", "missing"])
def test_replace_tags_undo_history(pair, replace_reference_ui, action, old):
    before = [collection.undo_status() for collection in pair[:2]]
    params = {"tag_to_replace": old, "replace_with_tag": "renamed"}
    if action == "replaceTags":
        params["notes"] = list(pair[0].find_notes(""))
    compare(pair, action, params)
    assert_mutation_state(pair)
    for collection, status in zip(pair[:2], before):
        if old == "missing":
            assert collection.undo_status() == status
        else:
            assert not collection.undo_status().undo


@pytest.mark.parametrize("action", ["updateNoteFields", "updateNote"])
@pytest.mark.parametrize("fields", [
    None, False, 0, "", [], ["Front"], {}, {"front": "ignored"},
    {"Front": 123}, {"Front": None}, {"Front": False}, {"Front": []}, {"Back": "updated"},
])
def test_note_update_field_values(pair, action, fields):
    compare(pair, action, {"note": {"id": pair[0].find_notes("")[0], "fields": fields}})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["updateNoteFields", "updateNote"])
@pytest.mark.parametrize("case", ["null", "false", "zero", "string", "float", "list", "map", "missing", "no-id", "no-fields"])
def test_note_update_id_and_field_presence(pair, action, case):
    nid = pair[0].find_notes("")[0]
    value = {"null": None, "false": False, "zero": 0, "string": str(nid), "float": float(nid),
             "list": [], "map": {}, "missing": 9999999999999, "no-id": nid, "no-fields": nid}[case]
    note = {"id": value, "fields": {"Back": "updated"}}
    if case in ("no-id", "no-fields"):
        note.pop("id" if case == "no-id" else "fields")
    compare(pair, action, {"note": note})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["updateNoteFields", "updateNote"])
def test_note_field_update_clears_undo(pair, action):
    compare(pair, action, {"note": {"id": pair[0].find_notes("")[0], "fields": {"Back": "updated"}}})
    assert_mutation_state(pair)
    for collection in pair[:2]:
        assert not collection.undo_status().undo


@pytest.mark.parametrize("change", [
    {}, {"id": None}, {"id": False}, {"modelName": None}, {"modelName": "Missing model"},
    {"modelName": 123}, {"fields": None}, {"fields": {}}, {"fields": []},
    {"fields": {"unknown": "ignored"}}, {"fields": {"Front": 123}}, {"fields": {"Front": None}},
    {"tags": None}, {"tags": False}, {"tags": "one two"}, {"tags": []},
    {"tags": ["one", "two"]}, {"tags": [123]}, {"tags": {"tag": True}},
])
def test_update_note_model_options(pair, change):
    note = {"id": pair[0].find_notes("")[0], "modelName": "Basic", "fields": {"front": "replaced"}}
    note.update(change)
    reply = compare(pair, "updateNoteModel", {"note": note})
    assert_mutation_state(pair)
    if reply["error"] is None:
        for collection in pair[:2]:
            assert not collection.undo_status().undo


@pytest.mark.parametrize("missing", [
    ["id"], ["modelName"], ["fields"], ["id", "modelName"],
    ["id", "fields"], ["modelName", "fields"], ["id", "modelName", "fields"],
])
def test_update_note_model_missing_options(pair, missing):
    note = {"id": pair[0].find_notes("")[0], "modelName": "Basic", "fields": {"Front": "changed"}}
    for key in missing:
        note.pop(key)
    compare(pair, "updateNoteModel", {"note": note})
    assert_mutation_state(pair)


@pytest.mark.parametrize("case", ["string", "float", "list", "map", "missing"])
def test_update_note_model_raw_ids(pair, case):
    nid = pair[0].find_notes("")[0]
    value = {"string": str(nid), "float": float(nid), "list": [nid],
             "map": {"id": nid}, "missing": 9999999999999}[case]
    compare(pair, "updateNoteModel", {
        "note": {"id": value, "modelName": "Basic", "fields": {"Front": "changed"}},
    })
    assert_mutation_state(pair)


@pytest.mark.parametrize("model_name,fields", [
    ("Basic (and reversed card)", {"front": "changed", "BACK": "answer"}),
    ("Cloze", {"text": "{{c1::one}} and {{c2::two}}", "Back Extra": "extra"}),
])
@pytest.mark.parametrize("reviewed", [False, True])
@pytest.mark.parametrize("tags", [None, ["converted"]])
def test_update_note_model_conversion(pair, model_name, fields, reviewed, tags):
    nid = pair[0].find_notes("")[0]
    if reviewed:
        for collection in pair[:2]:
            card = collection.get_note(nid).cards()[0]
            card.type = card.queue = 2
            card.ivl, card.due, card.factor, card.reps = 17, 23, 2500, 4
            collection.update_card(card)
    note = {"id": nid, "modelName": model_name, "fields": fields}
    if tags is not None:
        note["tags"] = tags
    reply = compare(pair, "updateNoteModel", {"note": note})
    assert reply["error"] is None
    assert_mutation_state(pair)
    for collection in pair[:2]:
        updated = collection.get_note(nid)
        assert updated.mid == collection.models.by_name(model_name)["id"]
        assert updated.tags == (tags or [])
        assert not collection.undo_status().undo


@pytest.mark.parametrize("action", ["addNote", "addNotes", "canAddNotes", "canAddNotesWithErrorDetail"])
@pytest.mark.parametrize("options", [
    None, False, True, 0, 1, "", "unknown", "allowDuplicate", [], ["unknown"],
    ["allowDuplicate"], {},
    {"allowDuplicate": None}, {"allowDuplicate": 1}, {"allowDuplicate": "false"},
    {"allowDuplicate": False}, {"allowDuplicate": True},
    {"duplicateScope": None}, {"duplicateScope": []}, {"duplicateScope": "deck"},
    {"duplicateScopeOptions": None}, {"duplicateScopeOptions": False},
    {"duplicateScopeOptions": 0}, {"duplicateScopeOptions": ""},
    {"duplicateScopeOptions": []}, {"duplicateScopeOptions": ["unknown"]},
    {"duplicateScopeOptions": "deckName"}, {"duplicateScopeOptions": ["checkChildren"]},
    {"duplicateScopeOptions": {"checkChildren": 1}},
    {"duplicateScopeOptions": {"checkAllModels": None}},
    {"duplicateScopeOptions": {"checkChildren": True, "checkAllModels": True}},
])
def test_note_creation_option_values(pair, action, options):
    note = {"deckName": "Parity::日本語", "modelName": "Basic",
            "fields": {"Front": "alpha", "Back": "one"}, "options": options}
    if action in ("addNote", "addNotes"):
        # A duplicate never allocates an ID unless the explicit boolean allows it.
        # Use empty content for that case, retaining an exact response comparison.
        if isinstance(options, dict) and options.get("allowDuplicate") is True:
            note["fields"]["Front"] = ""
    params = {"note": note} if action == "addNote" else {"notes": [note]}
    compare(pair, action, params)
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("action", ["addNote", "addNotes", "canAddNotes", "canAddNotesWithErrorDetail"])
@pytest.mark.parametrize("options", [None, False, {"allowDuplicate": 1},
                                     {"duplicateScopeOptions": {"checkChildren": "false"}}])
def test_note_creation_media_precedes_option_validation(pair, action, options):
    note = {"deckName": "Parity::日本語", "modelName": "Basic",
            "fields": {"Front": "new note"}, "options": options,
            "picture": {"filename": "before-options.txt", "data": "bWVkaWE=", "fields": ["Back"]}}
    params = {"note": note} if action == "addNote" else {"notes": [note]}
    compare(pair, action, params)
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("change", [
    {"isCloze": None}, {"isCloze": 0}, {"isCloze": 1}, {"isCloze": "false"},
    {"isCloze": []}, {"isCloze": {}}, {"css": False}, {"css": 123}, {"css": []},
    {"inOrderFields": None}, {"inOrderFields": False}, {"inOrderFields": "Front"},
    {"inOrderFields": [123]}, {"cardTemplates": None}, {"cardTemplates": False},
    {"cardTemplates": [None]}, {"cardTemplates": [{"Front": 123, "Back": "answer"}]},
    {"modelName": None}, {"modelName": False}, {"modelName": 123},
    {"modelName": []}, {"modelName": {}}, {"css": {}},
    {"inOrderFields": [None]}, {"inOrderFields": [False]}, {"inOrderFields": [{}]},
    {"cardTemplates": [False]}, {"cardTemplates": [123]}, {"cardTemplates": [[]]},
    {"cardTemplates": [{"Name": None, "Front": "{{Front}}", "Back": "{{Back}}"}]},
    {"cardTemplates": [{"Name": 123, "Front": "{{Front}}", "Back": "{{Back}}"}]},
    {"cardTemplates": [{"Front": "{{Front}}", "Back": None}]},
    {"isCloze": "false", "inOrderFields": ["Text"], "cardTemplates": [
        {"Front": "{{cloze:Text}}", "Back": "{{cloze:Text}}"}]},
])
def test_model_creation_raw_options(pair, change):
    test_model_creation(pair, change)


@pytest.mark.parametrize("action", [
    "addNote", "addNotes", "canAddNote", "canAddNoteWithErrorDetail",
    "canAddNotes", "canAddNotesWithErrorDetail", "updateNote", "updateNoteFields", "updateNoteModel",
])
@pytest.mark.parametrize("note", [None, False, 123, "", "id", [], ["id"], {}, {"unknown": True}])
def test_raw_note_containers(pair, action, note):
    params = {"notes": [note]} if action in ("addNotes", "canAddNotes", "canAddNotesWithErrorDetail") else {"note": note}
    compare(pair, action, params)
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("action", ["addNotes", "canAddNotes", "canAddNotesWithErrorDetail"])
@pytest.mark.parametrize("notes", [None, False, 123, "", "xy", [], {}, {"invalid": True}])
def test_raw_note_batch_containers(pair, action, notes):
    compare(pair, action, {"notes": notes})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("action", ["addNote", "addNotes", "canAddNote", "canAddNoteWithErrorDetail",
                                    "canAddNotes", "canAddNotesWithErrorDetail"])
@pytest.mark.parametrize("change", [
    {"modelName": None}, {"modelName": False}, {"modelName": 123}, {"modelName": []},
    {"deckName": None}, {"deckName": False}, {"deckName": 123}, {"deckName": []},
    {"fields": None}, {"fields": False}, {"fields": []}, {"fields": "Front"},
    {"fields": {"Front": 123}}, {"fields": {"Front": None}}, {"fields": {"Front": False}},
    {"fields": {"Front": []}}, {"fields": {"unknown": "ignored"}},
    {"tags": None}, {"tags": False}, {"tags": 123}, {"tags": "one two"}, {"tags": [123]},
])
def test_note_creation_raw_members(pair, action, change):
    note = {"modelName": "Basic", "deckName": "Parity::日本語",
            "fields": {"Front": "alpha", "Back": "one"}, **change}
    params = {"notes": [note]} if action in ("addNotes", "canAddNotes", "canAddNotesWithErrorDetail") else {"note": note}
    compare(pair, action, params)
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("action", ["addNotes", "canAddNotes", "canAddNotesWithErrorDetail"])
@pytest.mark.parametrize("malformed", [None, [], {}, {"modelName": "Missing"}])
def test_note_batch_keeps_media_around_invalid_entry(pair, action, malformed):
    def note(label):
        return {"modelName": "Basic", "deckName": "Parity::日本語",
                "fields": {"Front": label}, "picture": {
                    "filename": label + ".txt", "data": "bWVkaWE=", "fields": ["Back"]}}
    compare(pair, action, {"notes": [note("prefix"), malformed, note("suffix")]})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("action", ["updateModelTemplates", "updateModelStyling"])
@pytest.mark.parametrize("model", [None, False, 123, "", [], {}, {"name": "Missing"}, {"name": "Basic"}])
def test_model_update_raw_containers(pair, action, model):
    compare(pair, action, {"model": model})
    assert_mutation_state(pair)


@pytest.mark.parametrize("templates", [None, False, 123, "", [], {}, {"Unknown": 123},
    {"Card 1": None}, {"Card 1": False}, {"Card 1": []}, {"Card 1": 123}, {"Card 1": "x"},
    {"Card 1": {"Front": None}}, {"Card 1": {"Front": False}}, {"Card 1": {"Front": 123}},
    {"Card 1": {"Front": "{{Front}} changed", "Back": ["invalid"]}},
])
def test_model_template_raw_values(pair, templates):
    compare(pair, "updateModelTemplates", {"model": {"name": "Basic", "templates": templates}})
    assert_mutation_state(pair)


@pytest.mark.parametrize("css", [None, False, 123, "", [], {}, "body {color: red;}"])
def test_model_styling_raw_values(pair, css):
    compare(pair, "updateModelStyling", {"model": {"name": "Basic", "css": css}})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["addNote", "addNotes", "canAddNote", "canAddNoteWithErrorDetail",
                                    "canAddNotes", "canAddNotesWithErrorDetail"])
@pytest.mark.parametrize("missing", [
    ["modelName"], ["deckName"], ["fields"], ["modelName", "deckName"],
    ["modelName", "fields"], ["deckName", "fields"], ["modelName", "deckName", "fields"],
])
def test_note_creation_missing_members(pair, action, missing):
    note = {"modelName": "Basic", "deckName": "Parity::日本語", "fields": {"Front": "new"}}
    for key in missing:
        note.pop(key)
    params = {"notes": [note]} if action in ("addNotes", "canAddNotes", "canAddNotesWithErrorDetail") else {"note": note}
    compare(pair, action, params)
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("tags", [None, False, 123, "one two", [], ["one", "two"], [123], {"one": True}])
def test_note_creation_raw_tags_on_new_note(pair, tags):
    note = {"modelName": "Basic", "deckName": "Parity::日本語",
            "fields": {"Front": "brand new", "Back": "answer"}, "tags": tags}
    request = {"action": "addNote", "version": 6, "params": {"note": note}}
    expected = pair[2].handler(copy.deepcopy(request))
    actual = handle_ankiconnect_rpc(copy.deepcopy(request))
    assert actual["error"] == expected["error"]
    if actual["error"] is not None:
        assert actual == expected
        assert_note_and_media_state(pair)
        return
    # Successful insertion allocates independent note and card IDs.
    for response in (actual, expected):
        assert type(response["result"]) is int and response["result"] > 0
    notes = [c.get_note(r["result"]) for c, r in zip(pair[:2], (actual, expected))]
    assert notes[0].fields == notes[1].fields
    assert notes[0].tags == notes[1].tags
    assert notes[0].mid == notes[1].mid
    for n in notes:
        assert len(n.cards()) == 1
    for c, response in zip(pair[:2], (actual, expected)):
        c.remove_notes([response["result"]])
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("later", [123, {"Front": 123}, {"Back": 123}, None,
                                    {"Front": "{{Back}} suffix", "Back": "{{Front}}"}])
def test_model_template_saves_once_after_all_entries(pair, later):
    name = "Basic (and reversed card)"
    nid = pair[0].find_notes("")[0]
    compare(pair, "updateNoteModel", {"note": {
        "id": nid, "modelName": name, "fields": {"Front": "front", "Back": "back"}}})
    compare(pair, "updateModelTemplates", {"model": {"name": name, "templates": {
        "Card 1": {"Front": "{{Front}} prefix"}, "Card 2": later}}})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["updateModelTemplates", "updateModelStyling"])
@pytest.mark.parametrize("name", [None, False, 123, [], {}])
def test_model_update_raw_names(pair, action, name):
    compare(pair, action, {"model": {"name": name, "css": "", "templates": {}}})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action,change", [
    ("updateModelTemplates", {"templates": {"Card 1": {"Front": "{{Front}} undo check"}}}),
    ("updateModelStyling", {"css": "body {color: red;}"}),
])
def test_model_update_undo_redo(pair, action, change):
    compare(pair, action, {"model": {"name": "Basic", **change}})
    assert_mutation_state(pair)
    for c in pair[:2]:
        c.undo()
    assert_mutation_state(pair)
    for c in pair[:2]:
        c.redo()
    assert_mutation_state(pair)


_MODEL_MEMBER_ACTIONS = [
    ("modelFieldRename", {"oldFieldName": "Front", "newFieldName": "Renamed"}, "newFieldName"),
    ("modelFieldReposition", {"fieldName": "Front", "index": 1}, "index"),
    ("modelFieldAdd", {"fieldName": "Extra"}, "fieldName"),
    ("modelFieldRemove", {"fieldName": "Back"}, "fieldName"),
    ("modelFieldSetFont", {"fieldName": "Front", "font": "Arial"}, "font"),
    ("modelFieldSetFontSize", {"fieldName": "Front", "fontSize": 20}, "fontSize"),
    ("modelFieldSetDescription", {"fieldName": "Front", "description": "text"}, "description"),
    ("modelTemplateRename", {"oldTemplateName": "Card 1", "newTemplateName": "Renamed"}, "newTemplateName"),
    ("modelTemplateReposition", {"templateName": "Card 1", "index": 1}, "index"),
    ("modelTemplateAdd", {"template": {"Name": "Extra", "Front": "{{Front}}", "Back": "{{Back}}"}}, "template"),
    ("modelTemplateRemove", {"templateName": "Card 1"}, "templateName"),
]


@pytest.mark.parametrize("action,params,parameter", _MODEL_MEMBER_ACTIONS)
@pytest.mark.parametrize("value", [None, False, True, 0, 1, -1, 999, 1.5, "", "1", [], {}])
def test_model_member_raw_values(pair, action, params, parameter, value):
    compare(pair, action, {"modelName": "Basic", **params, parameter: value})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action,params,parameter", _MODEL_MEMBER_ACTIONS)
@pytest.mark.parametrize("name", [None, False, 123, [], {}, "Missing model"])
def test_model_member_lookup_precedes_value_validation(pair, action, params, parameter, name):
    compare(pair, action, {"modelName": name, **params, parameter: None})
    assert_mutation_state(pair)


@pytest.mark.parametrize("field", ["Extra", "Front"])
@pytest.mark.parametrize("index", [None, False, True, -1, 99, 1.5, "1", [], {}])
def test_model_field_add_raw_index_and_partial_write(pair, field, index):
    compare(pair, "modelFieldAdd", {"modelName": "Basic", "fieldName": field, "index": index})
    assert_mutation_state(pair)


@pytest.mark.parametrize("template", [
    {}, {"Name": "Extra"}, {"Name": "Extra", "Front": "{{Front}}"},
    {"Name": None, "Front": "{{Front}}", "Back": "{{Back}}"},
    {"Name": "Extra", "Front": 123, "Back": "{{Back}}"},
    {"Name": "Card 1", "Front": 123, "Back": None},
    {"Name": "Card 1", "Front": "", "Back": ""},
])
def test_model_template_add_raw_members(pair, template):
    compare(pair, "modelTemplateAdd", {"modelName": "Basic", "template": template})
    assert_mutation_state(pair)


@pytest.mark.parametrize("scope", [None, "deck", "collection", "unknown"])
@pytest.mark.parametrize("scope_deck", [None, "Parity", "Parity::日本語", "Missing deck"])
@pytest.mark.parametrize("children", [False, True])
@pytest.mark.parametrize("all_models", [False, True])
@pytest.mark.parametrize("model_name,fields", [
    ("Basic", {"Front": "alpha", "Back": "one"}),
    ("Basic (and reversed card)", {"Front": "alpha", "Back": "one"}),
])
def test_duplicate_scope_decks_and_models(pair, scope, scope_deck, children, all_models, model_name, fields):
    note = {"deckName": "Parity::日本語", "modelName": model_name, "fields": fields,
            "options": {"duplicateScope": scope, "duplicateScopeOptions": {
                "deckName": scope_deck, "checkChildren": children, "checkAllModels": all_models}}}
    compare(pair, "canAddNotesWithErrorDetail", {"notes": [note]})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("options", [{}, {"duplicateScope": "deck"},
    {"duplicateScopeOptions": {"checkAllModels": True}},
    {"duplicateScope": "deck", "duplicateScopeOptions": {"deckName": "Missing deck"}}])
@pytest.mark.parametrize("model_name,fields", [
    ("Basic", {"Front": " ", "Back": "answer"}),
    ("Basic", {"Front": "<b></b>", "Back": "answer"}),
    ("Basic", {"Front": "<b>alpha</b>", "Back": "answer"}),
    ("Cloze", {"Text": "plain text without deletion"}),
    ("Cloze", {"Text": "{{c1::alpha}}"}),
    ("Cloze", {"Text": "{{c0::alpha}}"}),
])
def test_duplicate_scope_empty_html_and_cloze(pair, options, model_name, fields):
    note = {"deckName": "Parity::日本語", "modelName": model_name, "fields": fields, "options": options}
    compare(pair, "canAddNotesWithErrorDetail", {"notes": [note]})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("action,params,parameter", [case for case in _MODEL_MEMBER_ACTIONS
    if case[0] not in ("modelFieldAdd", "modelTemplateAdd")])
@pytest.mark.parametrize("name", [None, False, [], {}, "Missing member"])
def test_model_member_raw_target_names(pair, action, params, parameter, name):
    target = next(key for key in ("oldFieldName", "fieldName", "oldTemplateName", "templateName") if key in params)
    compare(pair, action, {"modelName": "Basic", **params, target: name})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action,params,parameter", _MODEL_MEMBER_ACTIONS)
def test_model_member_undo_redo(pair, action, params, parameter):
    # Give template removal/reposition two templates and generated cards.
    if action.startswith("modelTemplate"):
        model_name = "Basic (and reversed card)"
        compare(pair, "updateNoteModel", {"note": {"id": pair[0].find_notes("")[0],
            "modelName": model_name, "fields": {"Front": "front", "Back": "back"}}})
    else:
        model_name = "Basic"
    if action == "modelTemplateAdd":
        params = {**params, "template": {**params["template"], "Front": "{{Front}} extra"}}
    reply = compare(pair, action, {"modelName": model_name, **params})
    assert reply["error"] is None
    assert_mutation_state(pair)
    for c in pair[:2]:
        c.undo()
    assert_mutation_state(pair)
    for c in pair[:2]:
        c.redo()
    assert_mutation_state(pair)


@pytest.mark.parametrize("scope_deck", [None, False, 123, [], {}, "Other"])
@pytest.mark.parametrize("all_models", [False, True])
def test_duplicate_scope_raw_deck_names(pair, scope_deck, all_models):
    note = {"modelName": "Basic", "deckName": "Parity::日本語", "fields": {"Front": "alpha"},
        "options": {"duplicateScope": "deck", "duplicateScopeOptions": {
            "deckName": scope_deck, "checkAllModels": all_models}}}
    compare(pair, "canAddNotesWithErrorDetail", {"notes": [note]})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("scope_deck", ["Parity::日本語", "Other"])
@pytest.mark.parametrize("original_deck", [False, True])
def test_duplicate_scope_uses_current_card_deck(pair, scope_deck, original_deck):
    for c in pair[:2]:
        card = c.get_note(c.find_notes("alpha")[0]).cards()[0]
        if original_deck:
            card.odid = card.did
        card.did = c.decks.id("Other")
        c.update_card(card)
    note = {"modelName": "Basic", "deckName": "Parity::日本語", "fields": {"Front": "alpha"},
        "options": {"duplicateScope": "deck", "duplicateScopeOptions": {"deckName": scope_deck}}}
    compare(pair, "canAddNotesWithErrorDetail", {"notes": [note]})
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("parameter", ["modelName", "findText", "replaceText", "front", "back", "css"])
@pytest.mark.parametrize("value", [None, False, True, 0, 1, "", "false", [], {}, ["x"]])
def test_model_find_replace_raw_values(pair, parameter, value):
    params = {"modelName": "Basic", "findText": "{{Front}}", "replaceText": "{{Front}} changed",
              parameter: value}
    compare(pair, "findAndReplaceInModels", params)
    assert_mutation_state(pair)


@pytest.mark.parametrize("flags", [False, None, "", [], {}, "false", 1])
@pytest.mark.parametrize("find,replace", [(None, None), ("absent text", None), ("{{Front}}", None)])
def test_model_find_replace_flags_defer_invalid_text(pair, flags, find, replace):
    compare(pair, "findAndReplaceInModels", {"modelName": "Basic", "findText": find,
        "replaceText": replace, "front": flags, "back": flags, "css": flags})
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["modelFieldNames", "modelFieldDescriptions", "modelFieldFonts",
    "modelFieldsOnTemplates", "modelTemplates", "modelStyling"])
@pytest.mark.parametrize("name", [None, False, True, 0, 123, "", [], {}, "Missing model", "Basic"])
def test_model_read_raw_names(pair, action, name):
    compare(pair, action, {"modelName": name})
    assert_mutation_state(pair)


@pytest.mark.parametrize("names", [None, False, 123, "", "Basic", [], {}, {"Basic": 1},
    [None], [False], [123], [[]], [{}], ["Basic", "Basic"], ["Missing", None], [None, "Missing"]])
def test_model_read_raw_name_lists(pair, names):
    compare(pair, "findModelsByName", {"modelNames": names})
    assert_mutation_state(pair)


@pytest.mark.parametrize("case", ["null", "false", "true", "zero", "negative", "missing", "string",
    "float", "fraction", "empty-list", "empty-map", "list", "map", "invalid-string"])
@pytest.mark.parametrize("action", ["modelNameFromId", "findModelsById"])
@pytest.mark.parametrize("warm_cache", [False, True])
def test_model_read_raw_ids(pair, action, case, warm_cache):
    mid = pair[0].models.by_name("Basic")["id"]
    value = {"null": None, "false": False, "true": True, "zero": 0, "negative": -1,
             "missing": 9999999999999, "string": str(mid), "float": float(mid), "fraction": mid + 0.5,
             "empty-list": [], "empty-map": {}, "list": [mid], "map": {"id": mid}, "invalid-string": "bad"}[case]
    # Anki's model cache accepts a float equal to a cached integer key; a cold
    # backend lookup rejects it. Compare the same cache state on both sides.
    for c in pair[:2]:
        c.models._clear_cache()
        if warm_cache:
            c.models.get(mid)
    params = {"modelIds": [value]} if action == "findModelsById" else {"modelId": value}
    compare(pair, action, params)
    assert_mutation_state(pair)


@pytest.mark.parametrize("case", ["null", "false", "scalar", "string", "empty-map", "map", "duplicates", "mixed"])
def test_model_read_raw_id_containers(pair, case):
    mid = pair[0].models.by_name("Basic")["id"]
    values = {"null": None, "false": False, "scalar": mid, "string": str(mid), "empty-map": {},
              "map": {str(mid): True}, "duplicates": [mid, mid], "mixed": [mid, "bad", None]}[case]
    compare(pair, "findModelsById", {"modelIds": values})
    assert_mutation_state(pair)


@pytest.mark.parametrize("bad_part", ["css", "qfmt", "afmt"])
def test_model_find_replace_keeps_saved_prefix(pair, bad_part):
    for c in pair[:2]:
        names = c.models.allNames()
        assert len(names) > 1
        later = c.models.by_name(names[1])
        if bad_part == "css":
            later["css"] = None
        else:
            later["tmpls"][0][bad_part] = None
    reply = compare(pair, "findAndReplaceInModels", {"modelName": None,
        "findText": "arial", "replaceText": "verdana"})
    assert reply["error"] is not None
    assert_mutation_state(pair)
    # assert_mutation_state clears model caches; this verifies the earlier save.
    for c in pair[:2]:
        assert "verdana" in c.models.by_name(names[0])["css"]


@pytest.mark.parametrize("name", [None, "Basic"])
@pytest.mark.parametrize("find,replacement", [("not present", "replacement"), ("arial", "verdana"), ("arial", "arial")])
def test_model_find_replace_undo_redo(pair, name, find, replacement):
    compare(pair, "findAndReplaceInModels", {"modelName": name, "findText": find, "replaceText": replacement})
    assert_mutation_state(pair)
    steps = len(pair[0].models.allNames()) if name is None else 1
    for _ in range(steps):
        for c in pair[:2]:
            c.undo()
        assert_mutation_state(pair)
    for _ in range(steps):
        for c in pair[:2]:
            c.redo()
        assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["modelTemplates", "modelFieldsOnTemplates", "findModelsByName"])
@pytest.mark.parametrize("front", [None, 123, [], ""])
def test_model_reads_keep_unsaved_template_values(pair, action, front):
    compare(pair, "modelTemplateAdd", {"modelName": "Basic", "template": {
        "Name": "Card 1", "Front": front, "Back": "{{Back}}"}})
    params = {"modelNames": ["Basic"]} if action == "findModelsByName" else {"modelName": "Basic"}
    compare(pair, action, params)
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["findModelsByName", "findModelsById"])
def test_model_lookup_multi_keeps_cached_reference(pair, action):
    mid = pair[0].models.by_name("Basic")["id"]
    lookup = {"modelNames": ["Basic"]} if action == "findModelsByName" else {"modelIds": [mid]}
    compare(pair, "multi", {"actions": [
        {"action": action, "params": lookup},
        {"action": "modelTemplateAdd", "params": {"modelName": "Basic", "template": {
            "Name": "Card 1", "Front": "{{Front}} changed in batch", "Back": "{{Back}}"}}},
    ]})
    assert_mutation_state(pair)


def normalized_created_model(model):
    """Keep the returned schema/values; normalize independently allocated IDs/time."""
    model = copy.deepcopy(model)
    assert isinstance(model["id"], int) and model["id"] > 0
    assert isinstance(model["mod"], int)
    model["id"], model["mod"] = "<allocated>", "<timestamp>"
    for member in model["flds"] + model["tmpls"]:
        if isinstance(member.get("id"), int):
            member["id"] = "<allocated>"
    return model


@pytest.mark.parametrize("change", [
    {},
    {"css": ""},
    {"css": ".card {color: red;}"},
    {"isCloze": True, "inOrderFields": ["Text"], "cardTemplates": [
        {"Front": "{{cloze:Text}}", "Back": "{{cloze:Text}}"}]},
    {"inOrderFields": []},
    {"cardTemplates": []},
    {"modelName": "Basic"},
    {"inOrderFields": ["Front", "Front"]},
    {"cardTemplates": [{"Front": "{{Missing}}", "Back": "{{Back}}"}]},
    {"cardTemplates": [{"Back": "{{Back}}"}]},
    {"cardTemplates": [{"Front": "{{Front}}"}]},
    {"cardTemplates": [{"Name": "", "Front": "{{Front}}", "Back": "{{Back}}"}]},
    {"cardTemplates": [
        {"Name": "Same", "Front": "{{Front}}", "Back": "{{Back}}"},
        {"Name": "Same", "Front": "{{Back}}", "Back": "{{Front}}"}]},
])
def test_model_creation(pair, change):
    params = {"modelName": "Created model", "inOrderFields": ["Front", "Back"],
              "cardTemplates": [{"Front": "{{Front}}", "Back": "{{Back}}"}], **change}
    request = {"action": "createModel", "version": 6, "params": params}
    expected = pair[2].handler(copy.deepcopy(request))
    actual = handle_ankiconnect_rpc(copy.deepcopy(request))
    actual, expected = json.loads(json.dumps(actual)), json.loads(json.dumps(expected))
    assert actual.keys() == expected.keys()
    assert actual["error"] == expected["error"]
    if expected["error"] is not None:
        assert actual == expected
        assert_mutation_state(pair)
        return
    actual_model = normalized_created_model(actual["result"])
    expected_model = normalized_created_model(expected["result"])
    assert actual_model == expected_model, first_difference(actual_model, expected_model)
    for collection in pair[:2]:
        collection.models._clear_cache()
    saved = [normalized_created_model(c.models.by_name(params["modelName"])) for c in pair[:2]]
    assert saved[0] == saved[1], first_difference(*saved)
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("params", [
    {"modelName": "Basic", "findText": "{{Front}}", "replaceText": "changed {{Front}}"},
    {"modelName": "Basic", "findText": "not present", "replaceText": "replacement"},
    {"modelName": None, "findText": "not present", "replaceText": "replacement"},
    {"modelName": None, "findText": "Arial", "replaceText": "serif", "front": False, "back": False},
    {"modelName": "Basic", "findText": "Front", "replaceText": "Back", "front": False, "css": False},
    {"modelName": "Basic", "findText": "", "replaceText": "", "front": False, "back": False, "css": False},
    {"modelName": "missing", "findText": "x", "replaceText": "y"},
])
def test_model_replacement_side_effects(pair, params):
    compare(pair, "findAndReplaceInModels", params)
    assert_mutation_state(pair)


@pytest.mark.parametrize("case", [
    "empty", "valid", "missing_card", "missing_card_id", "missing_ease",
    "invalid_ease", "missing_card_without_ease", "duplicate",
])
@pytest.mark.usefixtures("answer_clock")
def test_answer_cards_partial_mutations(pair, case):
    cards = list(pair[0].find_cards(""))
    first = {"cardId": cards[0], "ease": 4}
    cases = {
        "empty": [],
        "valid": [first, {"cardId": cards[1], "ease": 4}],
        "missing_card": [first, {"cardId": 9999999999999, "ease": 4}],
        "missing_card_id": [first, {"ease": 4}],
        "missing_ease": [first, {"cardId": cards[1]}],
        "invalid_ease": [first, {"cardId": cards[1], "ease": 0}],
        "missing_card_without_ease": [first, {"cardId": 9999999999999}],
        "duplicate": [first, first],
    }
    compare(pair, "answerCards", {"answers": cases[case]})
    assert_answer_state(pair)


@pytest.mark.parametrize("case", ["valid", "missing_ease", "invalid_ease"])
def test_answer_cards_backend_undo_redo(pair, monkeypatch, case):
    from anki.cards import Card

    monkeypatch.setattr(Card, "time_taken", lambda self, capped=True: 0)
    before = mutation_state(pair[0])
    cid = pair[0].find_cards("")[0]
    answers = [{"cardId": cid, "ease": 4}]
    if case != "valid":
        second = {"cardId": pair[0].find_cards("")[1]}
        if case == "invalid_ease":
            second["ease"] = 0
        answers.append(second)
    compare(pair, "answerCards", {"answers": answers})
    assert_mutation_state(pair)
    answered = mutation_state(pair[0])
    assert answered != before
    for collection in pair[:2]:
        collection.undo()
    assert_mutation_state(pair)
    assert mutation_state(pair[0]) == before
    for collection in pair[:2]:
        collection.redo()
    assert_mutation_state(pair)
    assert mutation_state(pair[0]) == answered


@pytest.mark.parametrize("suspend", [True, False])
@pytest.mark.parametrize("layout", [
    "empty", "one_matching", "two_matching", "three_matching", "mixed",
    "duplicates", "missing_visited", "missing_skipped",
])
def test_suspend_list_mutation(pair, suspend, layout):
    cards = list(pair[0].find_cards(""))
    matching_queue = -1 if suspend else 0
    for collection in pair[:2]:
        collection.db.execute("update cards set queue = ?", matching_queue)
    if layout == "mixed":
        for collection in pair[:2]:
            collection.db.execute("update cards set queue = ? where id = ?",
                                  0 if suspend else -1, cards[1])
    inputs = {
        "empty": [], "one_matching": cards[:1], "two_matching": cards[:2],
        "three_matching": cards, "mixed": cards, "duplicates": [cards[0]] * 3,
        "missing_visited": [9999999999999, cards[0]],
        "missing_skipped": [cards[0], 9999999999999],
    }
    compare(pair, "suspend", {"cards": inputs[layout], "suspend": suspend})
    assert_mutation_state(pair)


@pytest.mark.parametrize("case", [
    "empty", "valid", "two_rows", "duplicate_batch", "existing_conflict",
    "short", "long", "empty_row", "float", "numeric_string", "null_value",
    "bool_value", "non_numeric", "null_row",
])
def test_insert_reviews_atomicity_and_values(pair, case):
    cid = pair[0].find_cards("")[0]
    row = [1700000000001, cid, -1, 3, 5, 2, 2500, 1200, 1]
    second = [1700000000002, cid, -1, 4, 10, 5, 2600, 800, 1]
    rows = [row]
    if case == "empty":
        rows = []
    elif case == "two_rows":
        rows.append(second)
    elif case == "duplicate_batch":
        rows.append(row)
    elif case == "existing_conflict":
        for collection in pair[:2]:
            collection.db.execute("insert into revlog values (?,?,?,?,?,?,?,?,?)", *row)
        rows = [second, row]
    elif case == "short":
        rows = [row, second[:-1]]
    elif case == "long":
        rows = [row, second + [0]]
    elif case == "empty_row":
        rows = [row, []]
    elif case == "null_row":
        rows = [row, None]
    elif case in {"float", "numeric_string", "null_value", "bool_value", "non_numeric"}:
        second[6] = {"float": 2500.5, "numeric_string": "2600", "null_value": None,
                     "bool_value": True, "non_numeric": "bad"}[case]
        rows.append(second)
    compare(pair, "insertReviews", {"reviews": rows})
    assert pair[0].db.all("select * from revlog order by id") == pair[1].db.all(
        "select * from revlog order by id")
    assert_mutation_state(pair)


@pytest.mark.parametrize("action,extra", [
    ("areDue", {}), ("getIntervals", {}), ("getIntervals", {"complete": True}),
])
@pytest.mark.parametrize("state", [
    "reviewless", "missing", "mixed", "long_learning_due", "long_learning_future",
    "learning_threshold", "buried", "suspended",
])
def test_due_and_intervals_mixed_queues(pair, monkeypatch, action, extra, state):
    monkeypatch.setattr("time.time", lambda: 1700000000.75)
    cards = list(pair[0].find_cards(""))
    for collection in pair[:2]:
        collection.db.execute("update cards set type=2, queue=2, due=? where id=?",
                              collection.sched.today, cards[1])
        collection.db.execute("update cards set type=1, queue=1, due=? where id=?",
                              1699990000, cards[2])
        if state not in {"reviewless", "missing"}:
            for index, cid in enumerate(cards[1:], start=1):
                interval = {"long_learning_due": -1800, "long_learning_future": -7200,
                            "learning_threshold": -1200}.get(state, 5)
                collection.db.execute("insert into revlog values (?,?,?,?,?,?,?,?,?)",
                                      1699996400000 + index, cid, -1, 3, interval, 1, 2500, 0, 1)
        if state in {"buried", "suspended"}:
            collection.db.execute("update cards set queue=?", -2 if state == "buried" else -1)
    inputs = [cards[0], 9999999999999] if state == "missing" else [*cards, cards[1]]
    compare(pair, action, {"cards": inputs, **extra})


@pytest.mark.parametrize("action", ["getDeckStats", "cardReviews", "getLatestReviewID"])
@pytest.mark.parametrize("name", ["Missing deck", "Missing parent::日本語", "", "  padded  "])
def test_missing_deck_lookup_side_effects(pair, action, name):
    params = {"decks": [name]} if action == "getDeckStats" else {"deck": name}
    if action == "cardReviews":
        params["startID"] = 0
    compare(pair, action, params)
    assert sorted(d.name for d in pair[0].decks.all_names_and_ids()) == sorted(
        d.name for d in pair[1].decks.all_names_and_ids())
    assert_note_and_media_state(pair)


@pytest.mark.parametrize("action,params", [
    ("deckNames", {"unexpected": True}),
    ("modelNames", {"unexpected": True}),
    ("findCards", {}),
    ("findCards", {"query": "", "unexpected": True}),
    ("getDeckStats", {}),
    ("cardReviews", {}),
    ("cardReviews", {"deck": "Must not be created"}),
    ("cardReviews", {"unexpected": True}),
    ("getLatestReviewID", {}),
    ("getLatestReviewID", {"deck": "Must not be created", "unexpected": True}),
    ("findAndReplaceInModels", {"findText": "x", "replaceText": "y"}),
    ("addTags", {"notes": [], "tags": "x", "unexpected": True}),
])
def test_argument_binding_before_lookup_or_mutation(pair, action, params):
    before = mutation_state(pair[0])
    decks_before = sorted(d.name for d in pair[0].decks.all_names_and_ids())
    compare(pair, action, params)
    assert_mutation_state(pair)
    assert mutation_state(pair[0]) == before
    for collection in pair[:2]:
        assert sorted(d.name for d in collection.decks.all_names_and_ids()) == decks_before


@pytest.mark.parametrize("action,params", [
    ("findCards", {"query": None}),
    ("findNotes", {"query": False}),
    ("getDeckStats", {"decks": None}),
    ("getDeckStats", {"decks": "Default"}),
    ("getLatestReviewID", {"deck": None}),
    ("cardReviews", {"deck": None, "startID": 0}),
    ("getIntervals", {"cards": None}),
    ("areDue", {"cards": None}),
])
def test_lookup_parameter_values(pair, action, params):
    compare(pair, action, params)
    assert sorted(d.name for d in pair[0].decks.all_names_and_ids()) == sorted(
        d.name for d in pair[1].decks.all_names_and_ids())


@pytest.mark.parametrize("action,parameter", [
    ("cardsInfo", "cards"), ("cardsModTime", "cards"), ("getDecks", "cards"),
    ("getReviewsOfCards", "cards"), ("getIntervals", "cards"), ("areDue", "cards"),
    ("notesInfo", "notes"), ("notesModTime", "notes"),
])
@pytest.mark.parametrize("case", [
    "null", "false", "true", "zero", "float", "empty-string", "text",
    "empty-list", "empty-map", "map", "scalar-id", "string-id",
    "string-list", "float-list", "boolean-list", "mixed-list", "id-map",
    "null-list", "false-list", "nested-list", "nested-map", "fractional-id",
])
def test_lookup_id_value_coercion(pair, action, parameter, case):
    ids = pair[0].find_notes("") if parameter == "notes" else pair[0].find_cards("")
    values = {
        "null": None, "false": False, "true": True, "zero": 0, "float": 1.5,
        "empty-string": "", "text": "invalid", "empty-list": [], "empty-map": {},
        "map": {"id": ids[0]}, "scalar-id": ids[0], "string-id": str(ids[0]),
        "string-list": [str(ids[0])], "float-list": [float(ids[0])],
        "boolean-list": [True, False], "mixed-list": [ids[0], "invalid", ids[-1]],
        "id-map": {str(ids[0]): True}, "null-list": [None], "false-list": [False],
        "nested-list": [[]], "nested-map": [{}], "fractional-id": [ids[0] + 0.5],
    }
    before = mutation_state(pair[0])
    compare(pair, action, {parameter: values[case]})
    assert_mutation_state(pair)
    assert mutation_state(pair[0]) == before


@pytest.mark.parametrize("action", ["getReviewsOfCards", "getIntervals", "areDue", "getDecks"])
@pytest.mark.parametrize("case", ["string", "float", "mixed"])
def test_lookup_raw_ids_with_review_history(pair, action, case):
    cid = pair[0].find_cards("")[0]
    for collection in pair[:2]:
        card = collection.get_card(cid)
        card.type = card.queue = 2
        card.ivl = 5
        card.due = collection.sched.today
        collection.update_card(card)
        collection.db.execute(
            "insert into revlog values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            1720000000000, cid, -1, 3, 5, 1, 2500, 100, 1,
        )
    ids = {"string": [str(cid)], "float": [float(cid)],
           "mixed": [cid, str(cid), float(cid), str(cid)]}[case]
    compare(pair, action, {"cards": ids})
    assert_mutation_state(pair)


def test_reference_signatures(upstream):
    from tools.upstream_reference import signature_manifest

    assert signature_manifest(upstream) == SIGNATURES
    assert all(not spec[2] and not spec[3] for spec in SIGNATURES.values())


@pytest.mark.parametrize("action", sorted(SIGNATURES))
def test_all_action_unexpected_arguments(pair, action):
    before = mutation_state(pair[0])
    reply = compare(pair, action, {"unexpected": True})
    assert "unexpected keyword argument" in reply["error"]
    assert mutation_state(pair[0]) == before
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", sorted(
    name for name, spec in SIGNATURES.items() if spec[0] and name != "requestPermission"))
def test_all_action_required_arguments(pair, action):
    before = mutation_state(pair[0])
    reply = compare(pair, action)
    assert "required positional argument" in reply["error"]
    assert mutation_state(pair[0]) == before
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["version", "createDeck", "requestPermission", "unknown"])
@pytest.mark.parametrize("params", [None, False, True, 0, 1, 1.5, "", "x", [], [{}]])
def test_http_parameter_containers(pair, client, action, params):
    payload = {"action": action, "version": 6, "params": params}
    before = mutation_state(pair[0])
    expected = pair[2].http_request(copy.deepcopy(payload))
    response = client.post("/", json=payload)
    assert response.status_code == 200
    actual = response.json()
    assert actual == expected, first_difference(actual, expected)
    assert mutation_state(pair[0]) == before
    assert_mutation_state(pair)


@pytest.mark.parametrize("payload", [
    None, False, 0, "", "request", [], [{}], {}, {"params": None},
    {"action": ""}, {"action": None}, {"action": []},
    {"action": "version", "version": None}, {"action": "version", "version": False},
    {"action": "version", "version": "6"}, {"action": "version", "version": 6.5},
    {"action": "version", "version": 6.0},
    {"action": False, "version": "6", "params": []},
    {"action": "", "params": None},
    {"action": "version", "params": ["日本語" * 40, {"z": 1, "a": 2}]},
])
def test_http_request_schema(pair, client, payload):
    expected = pair[2].http_request(copy.deepcopy(payload))
    response = client.post("/", content=json.dumps(payload), headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    actual = response.json()
    assert actual == expected, first_difference(actual, expected)
    assert_mutation_state(pair)


@pytest.mark.parametrize("origin", [
    None, "http://localhost", "chrome-extension://parity", "https://denied.test", "",
])
@pytest.mark.parametrize("content", [
    b"", b" ", b"\r\n\t", b"{not json", b'{"action":',
    b'{"action":"version",}', b'{"action":"version"} trailing',
    b'{\n"action": "version",\n}', b'{"action":"ver\x00sion"}',
    b"\xff", b'{"action":"\xc3("}',
    b'\xef\xbb\xbf{"action":"version"}',
    '{"action":"version"}'.encode("utf-16"),
    b"null", b"[]", b'{"action":"requestPermission","params":null}',
    b'{"action":"version","version":6}',
    b'{"action":"version","version":6,"extra":"\xe6\x97\xa5"}',
], ids=[
    "empty", "space", "whitespace", "unquoted-key", "truncated",
    "trailing-comma", "extra-data", "multiline", "control-character",
    "invalid-utf8", "invalid-continuation", "utf8-bom", "utf16",
    "null", "array", "invalid-permission", "valid", "valid-unicode",
])
def test_http_raw_bodies(upstream, client, content, origin):
    headers = {} if origin is None else {"Origin": origin}
    expected = upstream.http_raw_request(content, headers=headers)
    actual = client.post("/", content=content, headers=headers)
    assert actual.status_code == expected.status_code
    if expected.content:
        assert actual.json() == expected.json()
        assert actual.headers["content-type"] == expected.headers["content-type"]
    else:
        assert actual.content == b""


def test_http_schema_snapshot(upstream):
    from tsunagi.http.compat.request_validation import REQUEST_SCHEMA

    assert REQUEST_SCHEMA == upstream.request_schema


def test_http_schema_error_precedence(upstream):
    from itertools import product

    from tsunagi.http.compat.request_validation import request_error

    # Independent values and key order expose best_match selection differences.
    values = [None, False, 0, "", [], {}, 6.0]
    for action, version, params in product(values + ["version"], values, values):
        for keys in [("action", "version", "params"), ("params", "version", "action")]:
            data = dict(zip(("action", "version", "params"), (action, version, params)))
            payload = {key: data[key] for key in keys}
            expected = upstream.http_request(payload)
            error = expected.get("error") if isinstance(expected, dict) else None
            assert request_error(payload) == error, payload


@pytest.mark.parametrize("actions", [
    None, False, 0, 1.5, "", "x", {}, {"action": "version"}, [],
    [None], [False], [42], ["version"], [[]], [{}], [{"action": []}],
])
def test_multi_action_containers(pair, actions):
    compare(pair, "multi", {"actions": actions})
    assert_mutation_state(pair)


@pytest.mark.parametrize("malformed", [None, False, 42, "version", []])
def test_multi_invalid_entry_keeps_prefix_and_stops_suffix(pair, malformed):
    compare(pair, "multi", {"actions": [
        {"action": "createDeck", "params": {"deck": "Shape prefix"}},
        malformed,
        {"action": "createDeck", "params": {"deck": "Shape suffix"}},
    ]})
    for col in pair[:2]:
        assert col.decks.by_name("Shape prefix") is not None
        assert col.decks.by_name("Shape suffix") is None
    assert sorted(d.name for d in pair[0].decks.all_names_and_ids()) == sorted(
        d.name for d in pair[1].decks.all_names_and_ids())
    assert_mutation_state(pair)


def test_multi_nested_abort_is_contained_by_parent(pair):
    reply = compare(pair, "multi", {"actions": [
        {"action": "multi", "version": 6, "params": {"actions": [
            {"action": "createDeck", "params": {"deck": "Nested prefix"}},
            None,
            {"action": "createDeck", "params": {"deck": "Nested suffix"}},
        ]}},
        {"action": "version", "version": 6},
    ]})
    assert reply["result"][1] == {"result": 6, "error": None}
    for col in pair[:2]:
        assert col.decks.by_name("Nested prefix") is not None
        assert col.decks.by_name("Nested suffix") is None
    assert_mutation_state(pair)


def compare_nested(pair, children, **kwargs):
    """Compare nested replies, excluding the reference harness's module prefix."""
    request = {"action": "multi", "version": 6, "params": {"actions": children}}
    expected = pair[2].handler(copy.deepcopy(request))
    actual = handle_ankiconnect_rpc(copy.deepcopy(request), **kwargs)
    prefix = type(pair[2]).__module__ + "."

    def portable_errors(value):
        if isinstance(value, list):
            return [portable_errors(item) for item in value]
        if isinstance(value, dict):
            return {key: (
                item.removeprefix(prefix) if key == "error" and isinstance(item, str)
                and item.startswith(prefix + "AnkiConnect.") and "argument after **" in item
                else portable_errors(item)
            ) for key, item in value.items()}
        return value

    expected = portable_errors(json.loads(json.dumps(expected)))
    actual = json.loads(json.dumps(actual))
    assert actual == expected, first_difference(actual, expected)
    return actual


@pytest.mark.parametrize("action", ["version", "createDeck", "unknown"])
@pytest.mark.parametrize("params", [None, False, True, 0, 1, 1.5, "", "x", [], [{}]])
def test_nested_parameter_containers(pair, action, params):
    compare_nested(pair, [
        {"action": action, "version": 6, "params": params},
        {"action": "version", "version": 6},
    ])
    assert_mutation_state(pair)


@pytest.mark.parametrize("action", ["version", "unknown"])
@pytest.mark.parametrize("version", [None, False, True, 0, 4, 4.5, 6.0, "4", "6", [], {}, "invalid"])
def test_nested_version_values(pair, action, version):
    compare_nested(pair, [
        {"action": action, "version": version},
        {"action": "version", "version": 6},
    ])


@pytest.mark.parametrize("version", [None, "6", [], {}])
def test_nested_bad_version_fails_after_mutation(pair, version):
    compare_nested(pair, [
        {"action": "createDeck", "version": version, "params": {"deck": "Version effect"}},
        {"action": "deckNames", "version": 6},
    ])
    for col in pair[:2]:
        assert col.decks.by_name("Version effect") is not None
    assert_mutation_state(pair)


@pytest.mark.parametrize("version", [None, "6"])
def test_nested_argument_error_precedes_bad_version(pair, version):
    compare_nested(pair, [
        {"action": "createDeck", "version": version,
         "params": {"deck": "Must not be created", "unexpected": True}},
        {"action": "deckNames", "version": 6},
    ])
    for col in pair[:2]:
        assert col.decks.by_name("Must not be created") is None
    assert_mutation_state(pair)


@pytest.mark.parametrize("params", [
    {}, {"origin": ""}, {"allowed": True}, {"unexpected": True},
    {"origin": "", "allowed": True}, {"origin": None, "allowed": "yes"},
    {"origin": "https://unknown.test", "allowed": 1}, None, [], False,
])
def test_nested_permission_binding(pair, params):
    compare_nested(pair, [
        {"action": "requestPermission", "version": 6, "params": params},
        {"action": "version", "version": 6},
    ])


@pytest.mark.parametrize("origin", [None, "", "http://localhost", "https://unknown.test"])
def test_nested_permission_false_still_prompts(pair, monkeypatch, origin):
    from types import SimpleNamespace

    prompts = []

    class DeniedDialog:
        Icon = SimpleNamespace(Question=1)
        StandardButton = SimpleNamespace(Yes=1, No=2)

        def __init__(self, parent):
            prompts.append("upstream")

        def __getattr__(self, name):
            return lambda *args: None

        def exec(self):
            return self.StandardButton.No

        def checkBox(self):
            return SimpleNamespace(isChecked=lambda: False)

    namespace = pair[2].handler.__func__.__globals__
    monkeypatch.setitem(namespace, "QMessageBox", DeniedDialog)
    monkeypatch.setitem(namespace, "QCheckBox", lambda **kwargs: None)
    monkeypatch.setitem(namespace, "Qt", SimpleNamespace(WindowStaysOnTopHint=1))
    monkeypatch.setattr(pair[2], "window", lambda: SimpleNamespace(windowIcon=lambda: None))

    def deny(value):
        assert value == origin
        prompts.append("shim")
        return False

    reply = compare_nested(pair, [
        {"action": "requestPermission", "version": 6,
         "params": {"origin": origin, "allowed": False}},
    ], ask_permission=deny)
    assert reply["result"] == [{"result": {"permission": "denied"}, "error": None}]
    assert prompts == ["upstream", "shim"]
