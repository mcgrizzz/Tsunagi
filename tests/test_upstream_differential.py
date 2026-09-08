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
def test_answer_cards_partial_mutations(pair, monkeypatch, case):
    from anki.cards import Card

    # Answer execution time is an external input, not a shim behavior difference.
    monkeypatch.setattr(Card, "time_taken", lambda self, capped=True: 0)
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
    assert_mutation_state(pair)


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
