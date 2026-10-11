"""GET /v1/statistics/today and /v1/statistics/review-days (6.6): Anki's own counts."""
import time

import pytest


@pytest.fixture()
def cards(client, col):
    for front in "abc":
        client.post("/v1/notes", json={"noteTypeName": "Basic", "deckName": "Default",
                                       "fields": {"Front": front, "Back": ""}, "tags": ["stat"]})
    return col.find_cards("")


def review(col, cid, day, ivl=10, ms=5000):
    """A review on Anki day `day` (0 today, -1 yesterday): an hour after it started."""
    start = col.sched.day_cutoff - 86400 * (1 - day)
    rid = (start + 3600) * 1000 + cid % 1000
    col.db.execute("insert into revlog values (?,?,?,?,?,?,?,?,?)",
                   rid, cid, -1, 3, ivl, ivl, 2500, ms, 1)  # young or mature by lastIvl


def date_of(col, day):
    return time.strftime("%Y-%m-%d", time.localtime(col.sched.day_cutoff - 86400 * (1 - day)))


def test_today_counts_answers_by_kind(client, col, cards, answer_cards):
    assert answer_cards(3) == 3
    review(col, cards[0], 0, ivl=30, ms=2000)
    body = client.get("/v1/statistics/today").json()
    assert (body["reviews"], body["correct"], body["learn"], body["review"]) == (4, 4, 3, 1)
    assert body["mature"] == {"reviews": 1, "correct": 1}
    assert body["seconds"] >= 2


def test_search_keeps_the_reviews_of_the_cards_it_finds(client, col, cards, answer_cards):
    answer_cards(2)
    assert client.get("/v1/statistics/today", params={"search": "tag:stat"}).json()["reviews"] == 2
    assert client.get("/v1/statistics/today", params={"search": "tag:none"}).json()["reviews"] == 0
    days = client.get("/v1/statistics/review-days", params={"search": "tag:none"}).json()
    assert days["items"] == [] and days["streak"] == 0


def test_review_days_are_newest_first_with_the_streak(client, col, cards):
    for day in (0, -1, -2, -4):
        review(col, cards[0], day)
    review(col, cards[1], -1, ivl=30, ms=3000)
    body = client.get("/v1/statistics/review-days").json()
    assert [d["date"] for d in body["items"]] == [date_of(col, d) for d in (0, -1, -2, -4)]
    yesterday = body["items"][1]
    assert (yesterday["reviews"], yesterday["young"], yesterday["mature"]) == (2, 1, 1)
    assert yesterday["seconds"] == 8
    assert body["days_studied"] == 4 and body["streak"] == 3


def test_a_streak_holds_while_today_has_no_reviews_yet(client, col, cards):
    for day in (-1, -2):
        review(col, cards[0], day)
    assert client.get("/v1/statistics/review-days").json()["streak"] == 2


def test_days_limits_the_range_and_zero_is_all_history(client, col, cards):
    for day in (0, -1, -400):
        review(col, cards[0], day)
    assert client.get("/v1/statistics/review-days", params={"days": 2}).json()["days_studied"] == 2
    assert client.get("/v1/statistics/review-days").json()["days_studied"] == 2
    assert client.get("/v1/statistics/review-days", params={"days": 0}).json()["days_studied"] == 3


def test_a_bad_search_is_400(client, cards):
    resp = client.get("/v1/statistics/today", params={"search": "deck:("})
    assert resp.status_code == 400, resp.text
