"""POST /v1/cards:delete-empty (6.119): Anki's Tools > Empty Cards, with a dry run."""
import pytest
from access import key_required

ROUTE = "/v1/cards:delete-empty"


@pytest.fixture()
def empties(col):
    """A note whose Card 2 is empty, a cloze note whose cards are all empty, and a full note."""
    m = col.models
    half = col.new_note(m.by_name("Basic (and reversed card)"))
    half["Front"], half["Back"] = "f", "b"
    col.add_note(half, 1)
    half["Back"] = ""
    col.update_note(half)
    cloze = col.new_note(m.by_name("Cloze"))
    cloze["Text"] = "{{c1::x}} {{c2::y}}"
    col.add_note(cloze, 1)
    cloze["Text"] = "plain"
    col.update_note(cloze)
    full = col.new_note(m.by_name("Basic"))
    full["Front"] = "kept"
    col.add_note(full, 1)
    by_ord = lambda nid: sorted(col.card_ids_of_note(nid), key=lambda c: col.get_card(c).ord)
    return half.id, by_ord(half.id), cloze.id, by_ord(cloze.id), full.id


def test_a_dry_run_answers_what_would_go_and_deletes_nothing(client, col, empties):
    half, half_cards, cloze, cloze_cards, _full = empties
    count, undo = col.card_count(), col.undo_status().undo
    body = client.post(ROUTE, json={"dry_run": True}).json()
    assert body["notes"] == [
        {"note_id": half, "card_ids": [half_cards[1]], "note_deleted": False},
        {"note_id": cloze, "card_ids": [cloze_cards[1]], "note_deleted": False},
    ]
    assert (body["affected"], body["notes_deleted"], body["dry_run"]) == (2, 0, True)
    assert col.card_count() == count and col.undo_status().undo == undo


def test_deleting_keeps_notes_and_their_first_card_by_default(client, col, empties):
    half, half_cards, cloze, cloze_cards, full = empties
    resp = client.post(ROUTE)
    assert resp.status_code == 200 and resp.json()["affected"] == 2, resp.text
    assert col.card_ids_of_note(half) == [half_cards[0]]
    assert col.card_ids_of_note(cloze) == [cloze_cards[0]] and len(col.card_ids_of_note(full)) == 1
    col.undo()
    assert len(col.card_ids_of_note(half)) == 2


def test_keep_notes_false_deletes_notes_whose_cards_are_all_empty(client, col, empties):
    half, _half_cards, cloze, cloze_cards, _full = empties
    body = client.post(ROUTE, json={"keep_notes": False}).json()
    assert {"note_id": cloze, "card_ids": cloze_cards, "note_deleted": True} in body["notes"]
    assert body["notes_deleted"] == 1 and cloze not in col.find_notes("")
    assert half in col.find_notes("")


def test_nothing_empty_writes_nothing(client, col):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "x"
    col.add_note(note, 1)
    undo = col.undo_status().undo
    body = client.post(ROUTE).json()
    assert (body["notes"], body["affected"]) == ([], 0) and col.undo_status().undo == undo


def test_deleting_notes_needs_write_notes(client, col, empties, reset_settings):
    reset_settings.update(roles={"cards_only": {"name": "Cards only", "grants": ["read", "write:cards"]}},
                          **key_required("k", role="cards_only"))
    headers = {"X-Api-Key": "k"}
    assert client.post(ROUTE, json={"keep_notes": False}, headers=headers).status_code == 403
    assert client.post(ROUTE, headers=headers).status_code == 200
