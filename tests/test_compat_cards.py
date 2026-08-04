"""
Wire-shape golden tests for the AnkiConnect card actions.

Every expectation here is quoted from canonical (git.sr.ht/~foosoft/
anki-connect). Several return values look wrong and are relied on anyway -
unsuspend returning null, suspend returning False when there's nothing to do.
"""
import pytest

from tsunagi.http.compat import actions  # noqa: F401  (registers the handlers)
from tsunagi.http.compat.errors import CARD_NOT_FOUND

MISSING = 999999


def rpc(client, action, params=None, version=6):
    body = {"action": action, "version": version}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


def add_note(client, front="犬", back="dog", deck="Default"):
    return rpc(client, "addNote", {"note": {
        "deckName": deck, "modelName": "Basic",
        "fields": {"Front": front, "Back": back}}})["result"]


@pytest.fixture()
def cards(client):
    """Two cards, in a fixed order."""
    add_note(client, "犬", "dog")
    add_note(client, "猫", "cat")
    return client, rpc(client, "findCards", {"query": ""})["result"]


class TestEaseFactors:
    def test_get_returns_none_for_missing(self, cards):
        client, cids = cards
        result = rpc(client, "getEaseFactors", {"cards": [cids[0], MISSING]})["result"]
        assert result == [0, None]

    def test_set_returns_parallel_bools(self, cards):
        client, cids = cards
        result = rpc(client, "setEaseFactors",
                     {"cards": [cids[0], MISSING], "easeFactors": [4200, 4200]})["result"]
        assert result == [True, False]
        assert rpc(client, "getEaseFactors", {"cards": [cids[0]]})["result"] == [4200]


class TestSuspend:
    def test_suspend_returns_true_then_false(self, cards):
        client, cids = cards
        assert rpc(client, "suspend", {"cards": cids})["result"] is True
        # Nothing left to do the second time.
        assert rpc(client, "suspend", {"cards": cids})["result"] is False

    def test_unsuspend_returns_null(self, cards):
        client, cids = cards
        rpc(client, "suspend", {"cards": cids})
        # Canonical calls suspend() without returning its result.
        assert rpc(client, "unsuspend", {"cards": cids}) == {"result": None, "error": None}
        assert rpc(client, "areSuspended", {"cards": cids})["result"] == [False, False]

    def test_suspended_single_card(self, cards):
        client, cids = cards
        assert rpc(client, "suspended", {"card": cids[0]})["result"] is False
        rpc(client, "suspend", {"cards": [cids[0]]})
        assert rpc(client, "suspended", {"card": cids[0]})["result"] is True

    def test_suspended_missing_card_is_an_error(self, cards):
        client, _ = cards
        resp = rpc(client, "suspended", {"card": MISSING})
        assert resp["result"] is None
        assert resp["error"] == CARD_NOT_FOUND.format(MISSING)

    def test_are_suspended_reports_none_for_missing(self, cards):
        client, cids = cards
        # Unlike `suspended`, this one reports rather than raises.
        result = rpc(client, "areSuspended", {"cards": [cids[0], MISSING]})["result"]
        assert result == [False, None]

    def test_suspend_partial_batch(self, cards):
        client, cids = cards
        rpc(client, "suspend", {"cards": [cids[0]]})
        assert rpc(client, "suspend", {"cards": cids})["result"] is True
        assert rpc(client, "areSuspended", {"cards": cids})["result"] == [True, True]


class TestDueAndIntervals:
    def test_new_cards_are_due(self, cards):
        client, cids = cards
        assert rpc(client, "areDue", {"cards": cids})["result"] == [True, True]

    def test_intervals_are_zero_for_new_cards(self, cards):
        client, cids = cards
        assert rpc(client, "getIntervals", {"cards": cids})["result"] == [0, 0]

    def test_intervals_from_revlog(self, cards, col):
        client, cids = cards
        card = col.get_card(cids[0])
        card.type, card.queue = 2, 2       # no longer new
        col.update_card(card)
        # getIntervals reads the revlog directly, so write real rows.
        for ms, ivl in ((1700000000000, 1), (1700000100000, 4)):
            col.db.execute(
                "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor,"
                " time, type) values (?, ?, -1, 3, ?, 0, 2500, 1000, 1)",
                ms, card.id, ivl)
        assert rpc(client, "getIntervals", {"cards": [card.id]})["result"] == [4]
        assert rpc(client, "getIntervals",
                   {"cards": [card.id], "complete": True})["result"] == [[1, 4]]


class TestCardsInfo:
    def test_key_set_is_exact(self, cards):
        client, cids = cards
        (info,) = rpc(client, "cardsInfo", {"cards": [cids[0]]})["result"]
        assert set(info) == {
            "cardId", "fields", "fieldOrder", "question", "answer", "modelName",
            "ord", "deckName", "css", "factor", "interval", "note", "type",
            "queue", "due", "reps", "lapses", "left", "mod", "nextReviews", "flags",
        }

    def test_fields_are_a_name_keyed_map(self, cards):
        client, cids = cards
        (info,) = rpc(client, "cardsInfo", {"cards": [cids[0]]})["result"]
        assert info["fields"] == {"Front": {"value": "犬", "order": 0},
                                 "Back": {"value": "dog", "order": 1}}
        assert info["modelName"] == "Basic"
        assert info["deckName"] == "Default"
        # Anki's rendered question carries the notetype's <style> block.
        assert "犬" in info["question"] and "<style>" in info["question"]
        # Anki formats these for display, wrapping numbers in directional
        # isolates, so assert the shape rather than the exact text.
        assert len(info["nextReviews"]) == 4
        assert all(isinstance(s, str) and s for s in info["nextReviews"])

    def test_missing_card_is_an_empty_object(self, cards):
        client, cids = cards
        result = rpc(client, "cardsInfo", {"cards": [cids[0], MISSING]})["result"]
        # An empty dict, never null - input and output positions must line up.
        assert result[1] == {}
        assert len(result) == 2

    def test_cards_mod_time(self, cards):
        client, cids = cards
        result = rpc(client, "cardsModTime", {"cards": [cids[0], MISSING]})["result"]
        assert set(result[0]) == {"cardId", "mod"}
        assert result[0]["cardId"] == cids[0]
        assert result[1] == {}


class TestCardsToNotes:
    def test_dedupes_siblings(self, client):
        nid = add_note(client, "犬")
        cids = rpc(client, "findCards", {"query": ""})["result"]
        assert rpc(client, "cardsToNotes", {"cards": cids})["result"] == [nid]

    def test_skips_missing(self, cards):
        client, cids = cards
        result = rpc(client, "cardsToNotes", {"cards": cids + [MISSING]})["result"]
        assert len(result) == 2


class TestRescheduling:
    def test_set_due_date_returns_true(self, cards):
        client, cids = cards
        assert rpc(client, "setDueDate", {"cards": cids, "days": "5"})["result"] is True
        (info,) = rpc(client, "cardsInfo", {"cards": [cids[0]]})["result"]
        assert (info["type"], info["queue"], info["due"]) == (2, 2, 5)

    def test_forget_cards_returns_null(self, cards):
        client, cids = cards
        rpc(client, "setDueDate", {"cards": cids, "days": "5"})
        assert rpc(client, "forgetCards", {"cards": cids}) == {"result": None, "error": None}
        (info,) = rpc(client, "cardsInfo", {"cards": [cids[0]]})["result"]
        assert (info["type"], info["queue"]) == (0, 0)

    def test_relearn_cards(self, cards):
        client, cids = cards
        assert rpc(client, "relearnCards", {"cards": cids}) == {"result": None, "error": None}
        (info,) = rpc(client, "cardsInfo", {"cards": [cids[0]]})["result"]
        # The one action with no Anki API: a raw UPDATE to type=3, queue=1.
        assert (info["type"], info["queue"]) == (3, 1)


class TestAnswerCards:
    def test_parallel_bools(self, cards):
        client, cids = cards
        result = rpc(client, "answerCards", {"answers": [
            {"cardId": cids[0], "ease": 3},
            {"cardId": MISSING, "ease": 3}]})["result"]
        assert result == [True, False]

    def test_the_card_is_really_answered(self, cards):
        client, cids = cards
        rpc(client, "answerCards", {"answers": [{"cardId": cids[0], "ease": 2}]})
        info = rpc(client, "cardsInfo", {"cards": [cids[0]]})["result"][0]
        assert info["reps"] == 1
        # And the revlog row records which button was pressed.
        reviews = rpc(client, "getReviewsOfCards", {"cards": [cids[0]]})["result"]
        assert [r["ease"] for r in reviews[str(cids[0])]] == [2]

    def test_invalid_ease_is_canonicals_error(self, cards):
        client, cids = cards
        resp = rpc(client, "answerCards",
                   {"answers": [{"cardId": cids[0], "ease": 9}]})
        assert resp["result"] is None
        assert resp["error"] == "invalid ease"   # anki's own message, verbatim

    def test_missing_key_is_a_keyerror_string(self, cards):
        client, cids = cards
        resp = rpc(client, "answerCards", {"answers": [{"ease": 3}]})
        assert resp["result"] is None
        assert resp["error"] == "'cardId'"


class TestSetSpecificValueOfCard:
    def test_card_as_list_is_bare_false(self, cards):
        client, cids = cards
        resp = rpc(client, "setSpecificValueOfCard",
                   {"card": [cids[0]], "keys": ["factor"], "newValues": [2600]})
        assert resp == {"result": False, "error": None}

    def test_non_list_keys_is_bare_false(self, cards):
        client, cids = cards
        assert rpc(client, "setSpecificValueOfCard",
                   {"card": cids[0], "keys": "factor", "newValues": [2600]}
                   )["result"] is False
        assert rpc(client, "setSpecificValueOfCard",
                   {"card": cids[0], "keys": ["factor"], "newValues": 2600}
                   )["result"] is False

    def test_length_mismatch_is_bare_false(self, cards):
        client, cids = cards
        assert rpc(client, "setSpecificValueOfCard",
                   {"card": cids[0], "keys": ["factor", "flags"],
                    "newValues": [2600]})["result"] is False

    def test_risky_key_without_warning_check_is_bare_false(self, cards):
        client, cids = cards
        assert rpc(client, "setSpecificValueOfCard",
                   {"card": cids[0], "keys": ["reps"], "newValues": [5]}
                   )["result"] is False
        assert rpc(client, "cardsInfo", {"cards": [cids[0]]}
                   )["result"][0]["reps"] == 0    # nothing was written

    def test_risky_key_with_warning_check_writes(self, cards):
        client, cids = cards
        result = rpc(client, "setSpecificValueOfCard",
                     {"card": cids[0], "keys": ["reps"], "newValues": [5],
                      "warning_check": True})["result"]
        assert result == [True]
        assert rpc(client, "cardsInfo", {"cards": [cids[0]]}
                   )["result"][0]["reps"] == 5

    def test_null_warning_check_slips_the_guard(self, cards):
        # Canonical tests `warning_check is False` - a JSON null passes it.
        client, cids = cards
        result = rpc(client, "setSpecificValueOfCard",
                     {"card": cids[0], "keys": ["reps"], "newValues": [7],
                      "warning_check": None})["result"]
        assert result == [True]

    def test_plain_key_writes_without_the_flag(self, cards):
        client, cids = cards
        result = rpc(client, "setSpecificValueOfCard",
                     {"card": cids[0], "keys": ["factor"], "newValues": [2600]}
                     )["result"]
        assert result == [True]
        assert rpc(client, "getEaseFactors", {"cards": [cids[0]]}
                   )["result"] == [2600]

    def test_missing_card_is_nested_false_with_message(self, cards):
        client, _ = cards
        result = rpc(client, "setSpecificValueOfCard",
                     {"card": MISSING, "keys": ["factor"], "newValues": [2600]}
                     )["result"]
        assert len(result) == 1
        assert result[0][0] is False
        assert isinstance(result[0][1], str) and result[0][1]
