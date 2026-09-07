"""Opt-in comparisons with real upstream code on equivalent real collections.

TSUNAGI_ANKICONNECT_CHECKOUT=/path/to/pinned/checkout python -m pytest -q tests/test_upstream_differential.py
"""

import base64
import copy
import hashlib
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from tools.upstream_reference import load_reference
from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc


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
    expected = upstream.handler(copy.deepcopy(request))
    actual = handle_ankiconnect_rpc(copy.deepcopy(request))
    # JSON round trip reflects wire types (e.g. tuple/list, integer map keys).
    actual, expected = json.loads(json.dumps(actual)), json.loads(json.dumps(expected))
    assert actual == expected, first_difference(actual, expected)
    return actual


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
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

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
