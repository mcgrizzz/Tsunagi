"""Deck scope and check_all_models on the Tsunagi API's duplicate checks.

The scoped checks report the notes AnkiConnect would; the Shim's
canAddNotesWithErrorDetail is the reference for the duplicate decision.
"""

import pytest


def note(front, model="Basic", deck="Default", **options):
    fields = {"Text": front} if model == "Cloze" else {"Front": front, "Back": "x"}
    return {"modelName": model, "deckName": deck, "fields": fields, **options}


def ac_options(scope=None, **scope_options):
    opts = {"allowDuplicate": False}
    if scope:
        opts["duplicateScope"] = scope
    if scope_options:
        opts["duplicateScopeOptions"] = scope_options
    return opts


@pytest.fixture
def seeded(client, col):
    for name in ("A", "B", "P::C"):
        client.post("/v1/decks", json={"name": name})
    ids = {}
    for key, body in {
        "basic_a": note("犬", deck="A"),
        "reversed_b": note("犬", model="Basic (and reversed card)", deck="B"),
        "basic_child": note("猫", deck="P::C"),
    }.items():
        ids[key] = client.post("/v1/notes", json=body).json()["created"][0]["id"]
    return ids


def check(client, candidate):
    result = client.post("/v1/notes:check", json={"notes": [candidate]}).json()["results"][0]
    return result["state"], sorted(result["duplicate_note_ids"] or [])


CASES = [
    # candidate front, deck, scope, options -> expected matching notes
    ("犬", "Default", None, {}, ["basic_a"]),
    ("犬", "Default", None, {"checkAllModels": True}, ["basic_a", "reversed_b"]),
    ("犬", "A", "deck", {}, ["basic_a"]),
    ("犬", "B", "deck", {}, []),
    ("犬", "B", "deck", {"checkAllModels": True}, ["reversed_b"]),
    ("犬", "Default", "deck", {"deckName": "A"}, ["basic_a"]),
    ("猫", "P", "deck", {}, []),
    ("猫", "P", "deck", {"checkChildren": True}, ["basic_child"]),
    ("鳥", "Default", None, {"checkAllModels": True}, []),
]


@pytest.mark.parametrize("front,deck,scope,options,expected", CASES)
def test_scoped_duplicates_match_ankiconnect(client, seeded, front, deck, scope, options, expected):
    candidate = note(front, deck=deck)
    if scope:
        candidate["duplicateScope"] = scope
    if options:
        candidate["duplicateScopeOptions"] = options
    state, ids = check(client, candidate)
    assert ids == sorted(seeded[key] for key in expected)
    assert state == ("duplicate" if expected else "normal")

    shim = client.post("/", json={"action": "canAddNotesWithErrorDetail", "version": 6, "params": {
        "notes": [dict(note(front, deck=deck), options=ac_options(scope, **options))]}}).json()["result"][0]
    assert shim["canAdd"] == (not expected)


def test_creation_honors_the_scope(client, col, seeded):
    blocked = client.post("/v1/notes", json=note("犬", duplicateScopeOptions={"checkAllModels": True},
                                               model="Basic (and reversed card)", deck="A"))
    assert blocked.json()["failed"][0]["code"] == "duplicate"
    allowed = client.post("/v1/notes", json=note("犬", duplicateScope="deck", deck="B"))
    assert allowed.json()["created"]


def test_unknown_scope_deck_is_reported_not_ignored(client, seeded):
    candidate = note("犬", duplicateScope="deck", duplicateScopeOptions={"deckName": "Nope"})
    result = client.post("/v1/notes:check", json={"notes": [candidate]}).json()["results"][0]
    assert result["state"] == "invalid" and "Nope" in result["reason"]


def test_empty_and_cloze_checks_still_come_from_anki(client, seeded):
    state, _ = check(client, note("", duplicateScopeOptions={"checkAllModels": True}))
    assert state == "empty"
    state, _ = check(client, note("no cloze", model="Cloze", duplicateScopeOptions={"checkAllModels": True}))
    assert state == "missing_cloze"


def test_options_require_real_booleans(client):
    candidate = note("x", duplicateScopeOptions={"checkAllModels": "yes"})
    assert client.post("/v1/notes:check", json={"notes": [candidate]}).status_code == 422
