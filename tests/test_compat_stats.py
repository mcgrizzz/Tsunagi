"""
Wire-shape golden tests for the AnkiConnect stats actions, quoted from
canonical (git.sr.ht/~foosoft/anki-connect).

The two result shapes are easy to confuse and clients depend on both:
cardReviews returns ARRAYS in revlog column order, getReviewsOfCards returns a
map of card id to objects.
"""
import pytest

from tsunagi.http.compat import actions  # noqa: F401  (registers the handlers)

# revlog column order, as canonical returns it from cardReviews
ID, CID, USN, EASE, IVL, LAST_IVL, FACTOR, TIME, TYPE = range(9)


def rpc(client, action, params=None, version=6):
    body = {"action": action, "version": version}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


def add_note(client, front, deck="Default"):
    return rpc(client, "addNote", {"note": {
        "deckName": deck, "modelName": "Basic",
        "fields": {"Front": front, "Back": "x"}}})["result"]


@pytest.fixture()
def reviewed(client, col, answer_cards):
    """Two answered cards in JP, one untouched card in Other."""
    rpc(client, "createDeck", {"deck": "JP"})
    rpc(client, "createDeck", {"deck": "Other"})
    for front in ("犬", "猫"):
        add_note(client, front, deck="JP")
    add_note(client, "馬", deck="Other")
    col.decks.select(col.decks.by_name("JP")["id"])
    assert answer_cards(2) == 2
    return client


class TestCounts:
    def test_reviewed_today(self, reviewed):
        assert rpc(reviewed, "getNumCardsReviewedToday")["result"] == 2

    def test_reviewed_today_on_empty_collection(self, client):
        assert rpc(client, "getNumCardsReviewedToday")["result"] == 0

    def test_reviewed_by_day(self, reviewed):
        result = rpc(reviewed, "getNumCardsReviewedByDay")["result"]
        assert len(result) == 1
        (day, count) = result[0]
        assert count == 2
        assert len(day) == 10 and day[4] == "-" and day[7] == "-"   # YYYY-MM-DD

    def test_reviewed_by_day_is_empty_without_reviews(self, client):
        assert rpc(client, "getNumCardsReviewedByDay")["result"] == []


class TestCollectionStatsHTML:
    def test_returns_html(self, reviewed):
        result = rpc(reviewed, "getCollectionStatsHTML")["result"]
        assert isinstance(result, str) and "<" in result

    def test_whole_collection_flag_is_accepted(self, reviewed):
        assert rpc(reviewed, "getCollectionStatsHTML",
                   {"wholeCollection": False})["error"] is None


class TestCardReviews:
    def test_rows_are_arrays_in_revlog_order(self, reviewed):
        rows = rpc(reviewed, "cardReviews", {"deck": "JP", "startID": 0})["result"]
        assert len(rows) == 2
        row = rows[0]
        assert isinstance(row, list) and len(row) == 9
        assert row[EASE] == 3                        # "good"
        assert row[ID] > 1_500_000_000_000           # epoch ms

    def test_start_id_is_exclusive(self, reviewed):
        rows = rpc(reviewed, "cardReviews", {"deck": "JP", "startID": 0})["result"]
        newer = rpc(reviewed, "cardReviews",
                    {"deck": "JP", "startID": rows[0][ID]})["result"]
        assert [r[ID] for r in newer] == [rows[1][ID]]

    def test_scoped_to_the_deck(self, reviewed):
        assert rpc(reviewed, "cardReviews", {"deck": "Other", "startID": 0})["result"] == []

    def test_unknown_deck_is_empty_and_creates_nothing(self, reviewed):
        # DEVIATION: canonical resolves with decks.id(), which CREATES the deck
        # - a write as a side effect of a read.
        assert rpc(reviewed, "cardReviews",
                   {"deck": "NoSuchDeck", "startID": 0})["result"] == []
        assert "NoSuchDeck" not in rpc(reviewed, "deckNames")["result"]


class TestLatestReviewID:
    def test_returns_the_newest_id(self, reviewed):
        rows = rpc(reviewed, "cardReviews", {"deck": "JP", "startID": 0})["result"]
        assert rpc(reviewed, "getLatestReviewID",
                   {"deck": "JP"})["result"] == rows[-1][ID]

    def test_zero_without_reviews(self, reviewed):
        assert rpc(reviewed, "getLatestReviewID", {"deck": "Other"})["result"] == 0

    def test_unknown_deck_is_zero_and_creates_nothing(self, reviewed):
        assert rpc(reviewed, "getLatestReviewID", {"deck": "Nope"})["result"] == 0
        assert "Nope" not in rpc(reviewed, "deckNames")["result"]


class TestGetReviewsOfCards:
    def _cards(self, client, deck):
        return rpc(client, "findCards", {"query": f"deck:{deck}"})["result"]

    def test_maps_card_id_to_its_reviews(self, reviewed):
        (cid, *_) = self._cards(reviewed, "JP")
        result = rpc(reviewed, "getReviewsOfCards", {"cards": [cid]})["result"]
        # JSON object keys are strings, so the card id comes back as one.
        (reviews,) = result.values()
        assert len(reviews) == 1
        assert reviews[0]["ease"] == 3
        # The key already carries the card id, so the review omits it.
        assert set(reviews[0]) == {"id", "usn", "ease", "ivl", "lastIvl",
                                   "factor", "time", "type"}

    def test_every_requested_card_gets_an_entry(self, reviewed):
        unreviewed = self._cards(reviewed, "Other")[0]
        reviewed_cid = self._cards(reviewed, "JP")[0]
        result = rpc(reviewed, "getReviewsOfCards",
                     {"cards": [reviewed_cid, unreviewed]})["result"]
        assert len(result) == 2
        assert result[str(unreviewed)] == []

    def test_empty_input(self, reviewed):
        assert rpc(reviewed, "getReviewsOfCards", {"cards": []})["result"] == {}
