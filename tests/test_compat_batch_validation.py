"""Batch routing must preserve individual validation and collection boundaries."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
from test_compat_notes import note_spec, rpc

from tsunagi.http.compat.actions import notes as actions


def test_batch_matches_individual_checks(client, col):
    rpc(client, "addNote", {"note": note_spec()})
    specs = [
        note_spec(), note_spec("new"), note_spec(""),
        note_spec(model="missing"), note_spec(deck="missing"),
        note_spec(model=[]), note_spec(deck={}), {},
        note_spec(fields=None), note_spec(tags=None),
        note_spec(options={"allowDuplicate": True}),
        note_spec(options={"allowDuplicate": "yes"}),
        note_spec(options={"duplicateScope": "deck"}),
        note_spec(options={"duplicateScope": "collection",
                           "duplicateScopeOptions": {"checkAllModels": True}}),
        note_spec(model="Cloze", fields={"Text": "{{c1::test}}", "Back Extra": ""}),
        note_spec(fields={"front": "case", "Unknown": "ignored"}),
    ]
    expected = []
    for spec in specs:
        ok, error = actions._can_add(deepcopy(spec))
        expected.append({"canAdd": True} if ok else {"canAdd": False, "error": error})
    before = col.note_count()
    assert rpc(client, "canAddNotesWithErrorDetail", {"notes": specs}) == {
        "result": expected, "error": None,
    }
    assert rpc(client, "canAddNotes", {"notes": specs})["result"] == [
        entry["canAdd"] for entry in expected
    ]
    assert col.note_count() == before


def test_lookups_and_dispatch_are_bounded(client, col, monkeypatch):
    model_lookup = Mock(wraps=col.models.by_name)
    deck_lookup = Mock(wraps=col.decks.by_name)
    batch = Mock(wraps=actions.ac_check_notes)
    monkeypatch.setattr(col.models, "by_name", model_lookup)
    monkeypatch.setattr(col.decks, "by_name", deck_lookup)
    monkeypatch.setattr(actions, "ac_check_notes", batch)
    specs = [note_spec(str(i)) for i in range(130)]
    assert rpc(client, "canAddNotes", {"notes": specs})["result"] == [True] * 130
    assert [len(call.args[0]) for call in batch.call_args_list] == [64, 64, 2]
    assert model_lookup.call_count == deck_lookup.call_count == 3


def test_fresh_state_between_batches(client, col, monkeypatch):
    original = actions.ac_check_notes
    calls = 0

    def check(specs):
        nonlocal calls
        result = original(specs)
        calls += 1
        if calls == 1:
            deck = col.decks.by_name("Default")
            col.decks.rename(deck, "Renamed")
        return result

    monkeypatch.setattr(actions, "ac_check_notes", check)
    results = rpc(client, "canAddNotesWithErrorDetail", {
        "notes": [note_spec(str(i)) for i in range(65)],
    })["result"]
    assert results[:64] == [{"canAdd": True}] * 64
    assert results[64] == {"canAdd": False, "error": "deck was not found: Default"}


@pytest.mark.parametrize("notes", [
    [note_spec(), note_spec(audio=[])], [note_spec(), None],
    [note_spec(picture=None)], "abc", {"first": note_spec()},
])
def test_media_and_unusual_shapes_keep_individual_path(monkeypatch, notes):
    single = Mock(return_value=(True, None))
    batch = Mock(side_effect=AssertionError("batch path selected"))
    monkeypatch.setattr(actions, "_can_add", single)
    monkeypatch.setattr(actions, "ac_check_notes", batch)
    assert list(actions._can_add_many(notes)) == [(True, None)] * len(notes)
    assert single.call_count == len(notes)


def test_empty_batch_needs_no_collection(monkeypatch):
    monkeypatch.setattr(actions, "ac_check_notes", Mock(side_effect=AssertionError))
    assert list(actions._can_add_many([])) == []


def test_failed_dispatch_preserves_per_input_results_without_retry(monkeypatch):
    batch = Mock(side_effect=TimeoutError("busy"))
    monkeypatch.setattr(actions, "ac_check_notes", batch)
    assert list(actions._can_add_many([note_spec(), note_spec()])) == [
        (False, "busy"), (False, "busy"),
    ]
    batch.assert_called_once()
