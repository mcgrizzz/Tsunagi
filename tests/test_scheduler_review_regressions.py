"""Scheduler/review compatibility regressions without an upstream checkout."""

import pytest

from tsunagi.adapters.anki.reviews import card_intervals, cards_are_due
from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc


def rpc(action, **params):
    return handle_ankiconnect_rpc({"action": action, "version": 6, "params": params})


@pytest.fixture
def cards(col, client):
    ids = []
    for front in ["first scheduler card", "second scheduler card"]:
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = front
        col.add_note(note, col.decks.id("Default"))
        ids.append(note.card_ids()[0])
    return ids


@pytest.mark.parametrize("suspend", [True, False])
def test_repeated_suspend_retains_upstream_result_and_skipped_validation(col, cards, suspend):
    col.db.execute("update cards set queue=?", -1 if suspend else 0)
    assert rpc("suspend", cards=cards, suspend=suspend) == {"result": True, "error": None}
    assert rpc("suspend", cards=cards[:1], suspend=suspend) == {"result": False, "error": None}
    assert rpc("suspend", cards=[cards[0], 9999999999999], suspend=suspend) == {
        "result": True, "error": None,
    }
    assert rpc("suspend", cards=[9999999999999, cards[0]], suspend=suspend)["error"] == (
        "Card was not found: 9999999999999")
    assert all(col.get_card(cid).queue == (-1 if suspend else 0) for cid in cards)


def test_reviewless_reads_keep_native_defaults_and_shim_errors(col, cards):
    cid = cards[0]
    col.db.execute("update cards set type=2, queue=2, due=? where id=?", col.sched.today, cid)
    assert card_intervals([cid]) == [0]
    assert cards_are_due([cid]) == [True]
    for action in ["areDue", "getIntervals"]:
        assert rpc(action, cards=[cid]) == {"result": None, "error": "list index out of range"}
    assert rpc("getIntervals", cards=[cid, 9999999999999], complete=True) == {
        "result": [[], []], "error": None,
    }


def test_duplicate_review_insert_is_atomic_and_exposes_backend_error(col, cards):
    row = [1700000000001, cards[0], -1, 3, 5, 2, 2500, 0, 1]
    response = rpc("insertReviews", reviews=[row, row])
    assert response["result"] is None
    assert "UNIQUE constraint failed: revlog.id" in response["error"]
    assert col.db.scalar("select count(*) from revlog") == 0


@pytest.mark.parametrize("value,expected", [(2500.5, 2500.5), (True, 1), ("2600", 2600)])
def test_legacy_review_scalars_are_not_coerced_to_integer_first(col, cards, value, expected):
    row = [1700000000001, cards[0], -1, 3, 5, 2, value, 0, 1]
    assert rpc("insertReviews", reviews=[row]) == {"result": None, "error": None}
    assert col.db.scalar("select factor from revlog") == expected


@pytest.mark.parametrize("value", ["2500); DELETE FROM cards; --", "(SELECT count(*) FROM cards)"])
def test_review_sql_fragments_cannot_execute(col, cards, value):
    row = [1700000000001, cards[0], -1, 3, 5, 2, 2500, 0, 1]
    bad = [1700000000002, cards[0], -1, 3, 5, 2, value, 0, 1]
    assert rpc("insertReviews", reviews=[row, bad]) == {
        "result": None, "error": "review values must be scalar SQL literals",
    }
    assert col.db.scalar("select count(*) from revlog") == 0
    assert list(col.find_cards("")) == cards


def test_quoted_review_text_remains_a_literal(col, cards):
    value = "'1''; DELETE FROM cards; --'"
    row = [1700000000001, cards[0], -1, 3, 5, 2, value, 0, 1]
    assert rpc("insertReviews", reviews=[row]) == {"result": None, "error": None}
    assert col.db.scalar("select factor from revlog") == "1'; DELETE FROM cards; --"
    assert list(col.find_cards("")) == cards
