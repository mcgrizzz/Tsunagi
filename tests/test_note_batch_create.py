"""Batch result mapping, live duplicate checks, undo boundaries and events."""
from copy import deepcopy

import pytest
from test_event_results import emit_last
from test_event_results import subscription as subscription
from test_events_broker import recorded_ops as recorded_ops


def candidate(front, **overrides):
    return {"modelName": "Basic", "deckName": "Default",
            "fields": {"Front": front, "Back": "meaning"}, **overrides}


def create(client, notes):
    response = client.post("/v1/notes:batch-create", json={"notes": notes})
    assert response.status_code == 200, response.text
    return response.json()


def test_partial_success_maps_inputs_and_observes_earlier_additions(client, col):
    submitted = [candidate("first"), candidate("first"), candidate(""),
                 candidate("bad", modelName="missing"), candidate("last")]
    original = deepcopy(submitted)
    result = create(client, submitted)
    assert submitted == original
    assert [n["index"] for n in result["created"]] == [0, 4]
    assert [n["index"] for n in result["failed"]] == [1, 2, 3]
    assert [n["code"] for n in result["failed"]] == ["duplicate", "invalid_note", "invalid_note"]
    for saved, front in zip(result["created"], ["first", "last"]):
        assert col.get_note(saved["id"])["Front"] == front
        assert set(saved) == {"index", "id"}
        assert col.card_ids_of_note(saved["id"])
    assert all(item["message"] for item in result["failed"])


def test_duplicate_policy_and_failed_deck_do_not_block_later_notes(client):
    result = create(client, [candidate("same"), candidate("same", allowDuplicate=True),
                             candidate("other", deckName="missing"), candidate("other")])
    assert [n["index"] for n in result["created"]] == [0, 1, 3]
    assert result["failed"][0]["index"] == 2


@pytest.mark.parametrize("notes", [[], [candidate("")]])
def test_no_success_leaves_undo_history_unchanged(client, col, notes):
    before = col.undo_status()
    result = create(client, notes)
    assert result["created"] == []
    assert col.undo_status() == before


def test_undo_and_redo_cover_batch_without_touching_earlier_notes(client, col):
    earlier = create(client, [candidate("earlier")])["created"][0]["id"]
    batch = create(client, [candidate(str(i)) for i in range(40)])
    ids = [note["id"] for note in batch["created"]]
    col.undo()
    assert [note["id"] for note in client.get("/v1/notes").json()["items"]] == [earlier]
    col.redo()
    assert {note["id"] for note in client.get("/v1/notes").json()["items"]} == {earlier, *ids}


def test_malformed_request_adds_nothing(client, col):
    response = client.post("/v1/notes:batch-create", json={"notes": [candidate("valid"), {}]})
    assert response.status_code == 422
    assert client.get("/v1/notes").json()["items"] == []


def test_one_operation_emits_only_successful_note_and_card_ids(client, col, subscription, recorded_ops):
    result = create(client, [candidate("one"), candidate("one"), candidate("two")])
    assert len(recorded_ops) == 1
    event = emit_last(recorded_ops, subscription)
    assert event["notes.created"]["ids"] == [n["id"] for n in result["created"]]
    assert event["cards.created"]["ids"] == [cid for n in result["created"]
                                            for cid in col.card_ids_of_note(n["id"])]


def test_batch_reuses_only_setup_and_returns_ids_without_reloading_notes(client, col, monkeypatch):
    counts = {"model": 0, "deck": 0}
    for name, manager in [("model", col.models), ("deck", col.decks)]:
        original = manager.by_name
        def lookup(value, original=original, name=name):
            counts[name] += 1
            return original(value)
        monkeypatch.setattr(manager, "by_name", lookup)
    def unexpected(*args, **kwargs):
        pytest.fail("ID-only creation must not reload saved notes")
    monkeypatch.setattr(col, "get_note", unexpected)
    monkeypatch.setattr(col, "card_ids_of_note", unexpected)
    assert len(create(client, [candidate(str(i)) for i in range(40)])["created"]) == 40
    assert counts == {"model": 1, "deck": 1}


def test_duplicate_failure_does_not_search_for_existing_ids(client, col, monkeypatch):
    from tsunagi.adapters.anki import notes

    def unexpected(*args, **kwargs):
        pytest.fail("Batch failures need a reason, not another duplicate-ID lookup")
    monkeypatch.setattr(notes, "_duplicate_ids", unexpected)
    result = create(client, [candidate("same"), candidate("same")])
    assert len(result["created"]) == 1
    assert result["failed"] == [{"index": 1, "code": "duplicate",
                                  "message": "Note duplicates an existing note"}]
