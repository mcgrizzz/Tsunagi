"""
Writes keep Anki's undo history (backlog 6.53). A write without an undo entry
(skip_undo_entry=True, or raw SQL) wipes the whole history, so after one the
user could undo nothing, not even what they did before it.
"""
import ast
from pathlib import Path

import pytest

from tsunagi.http.compat import actions  # noqa: F401  (registers the handlers)

TSUNAGI = Path(__file__).resolve().parent.parent / "tsunagi"


def rpc(client, action, params):
    body = client.post("/", json={"action": action, "version": 6, "params": params}).json()
    assert body["error"] is None, body
    return body["result"]


@pytest.fixture()
def notes(client, col):
    """Two tagged Basic notes; the last undo step is adding the second."""
    ids = [rpc(client, "addNote", {"note": {"deckName": "Default", "modelName": "Basic",
                                            "fields": {"Front": front, "Back": ""}, "tags": ["old"]}})
           for front in ("犬", "猫")]
    assert col.undo_status().undo == "Add Note"
    return ids


def card_of(col, nid):
    return col.get_card(col.card_ids_of_note(nid)[0])


def check_undo(col, step, before, after):
    """The write is one undo step; undoing it restores the value and leaves the add undoable."""
    assert col.undo_status().undo == step
    assert after() != before
    col.undo()
    assert after() == before
    assert col.undo_status().undo == "Add Note"


def test_update_note_fields(client, col, notes):
    rpc(client, "updateNoteFields", {"note": {"id": notes[0], "fields": {"Back": "dog"}}})
    check_undo(col, "Update Note", "", lambda: col.get_note(notes[0])["Back"])


def test_update_note(client, col, notes):
    rpc(client, "updateNote", {"note": {"id": notes[0], "fields": {"Back": "dog"}}})
    check_undo(col, "Update Note", "", lambda: col.get_note(notes[0])["Back"])


def test_update_note_model(client, col, notes):
    basic = col.get_note(notes[0]).mid
    rpc(client, "updateNoteModel", {"note": {"id": notes[0], "modelName": "Basic (and reversed card)",
                                             "fields": {"Front": "犬", "Back": "dog"}, "tags": []}})
    check_undo(col, "Update Note", basic, lambda: col.get_note(notes[0]).mid)


def test_set_ease_factors_is_one_step(client, col, notes):
    rpc(client, "setEaseFactors", {"cards": [card_of(col, n).id for n in notes], "easeFactors": [3000, 3100]})
    check_undo(col, "Update Card", [0, 0], lambda: [card_of(col, n).factor for n in notes])


def test_set_specific_value_of_card(client, col, notes):
    rpc(client, "setSpecificValueOfCard", {"card": card_of(col, notes[0]).id, "keys": ["flags"], "newValues": [1]})
    check_undo(col, "Update Card", 0, lambda: card_of(col, notes[0]).flags)


def test_native_set_values(client, col, notes):
    r = client.post("/v1/cards:set-values", json={"card_id": card_of(col, notes[0]).id, "values": {"flags": 2}})
    assert r.status_code == 200, r.text
    check_undo(col, "Update Card", 0, lambda: card_of(col, notes[0]).flags)


@pytest.mark.parametrize("action,params", [
    ("replaceTags", {"tag_to_replace": "old", "replace_with_tag": "new"}),
    ("replaceTagsInAllNotes", {"tag_to_replace": "old", "replace_with_tag": "new"}),
])
def test_replace_tags_is_one_step(client, col, notes, action, params):
    rpc(client, action, {**params, **({"notes": notes} if action == "replaceTags" else {})})
    check_undo(col, "Update Note", [["old"], ["old"]], lambda: [col.get_note(n).tags for n in notes])


def test_relearn_cards(client, col, notes):
    cids = [card_of(col, n).id for n in notes]
    rpc(client, "relearnCards", {"cards": cids + [999999]})   # a missing card is skipped, as upstream
    check_undo(col, "Update Card", [(0, 0), (0, 0)],
               lambda: [(col.get_card(c).type, col.get_card(c).queue) for c in cids])


def test_no_write_skips_its_undo_entry():
    """Only raw review-row inserts clear undo: Anki has no undoable way to add them, and their docs say so."""
    calls = []
    for path in TSUNAGI.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and any(k.arg == "skip_undo_entry" for k in node.keywords):
                calls.append(f"{path.relative_to(TSUNAGI)}:{node.lineno}")
    assert calls == []
