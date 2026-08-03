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
