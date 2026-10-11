"""GET /v1/statistics/today and the /v1/review-days list (6.6): Anki's own counts."""
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
    assert body["duration_ms"] >= 2000


def test_search_keeps_the_reviews_of_the_cards_it_finds(client, col, cards, answer_cards):
    answer_cards(2)
    assert client.get("/v1/statistics/today", params={"search": "tag:stat"}).json()["reviews"] == 2
    assert client.get("/v1/statistics/today", params={"search": "tag:none"}).json()["reviews"] == 0
    assert client.get("/v1/review-days", params={"search": "tag:none"}).json()["items"] == []
    [today] = client.get("/v1/review-days", params={"search": "tag:stat"}).json()["items"]
    assert today["reviews"] == 2


def test_review_days_are_a_list_with_the_shared_parameters(client, col, cards):
    for day in (0, -1, -2, -4, -400):
        review(col, cards[0], day)
    review(col, cards[1], -1, ivl=30, ms=3000)
    body = client.get("/v1/review-days", params={"include": "total"}).json()
    assert [d["date"] for d in body["items"]] == [date_of(col, d) for d in (-400, -4, -2, -1, 0)]
    assert body["total"] == 5
    yesterday = body["items"][3]
    assert (yesterday["reviews"], yesterday["young"], yesterday["mature"]) == (2, 1, 1)
    assert yesterday["duration_ms"] == 8000
    recent = client.get("/v1/review-days", params={
        "where": f'date>="{date_of(col, -2)}"', "order": "date:desc", "limit": 2}).json()
    assert [d["date"] for d in recent["items"]] == [date_of(col, 0), date_of(col, -1)]
    rest = client.get("/v1/review-days", params={
        "where": f'date>="{date_of(col, -2)}"', "order": "date:desc", "limit": 2,
        "cursor": recent["next_cursor"]}).json()
    assert [d["date"] for d in rest["items"]] == [date_of(col, -2)]
    posted = client.post("/v1/review-days/query", json={"search": "tag:stat", "select": "date",
                                                         "shape": "scalar"}).json()
    assert posted["items"] == [date_of(col, d) for d in (-400, -4, -2, -1, 0)]


def test_the_streak_counts_days_in_a_row_up_to_today(client, col, cards):
    for day in (0, -1, -2, -4):
        review(col, cards[0], day)
    assert client.get("/v1/statistics/today").json()["streak"] == 3


def test_a_streak_holds_while_today_has_no_reviews_yet(client, col, cards):
    for day in (-1, -2):
        review(col, cards[0], day)
    assert client.get("/v1/statistics/today").json()["streak"] == 2


def test_a_bad_search_is_400(client, cards):
    assert client.get("/v1/statistics/today", params={"search": "deck:("}).status_code == 400
    assert client.get("/v1/review-days", params={"search": "deck:("}).status_code == 400
