"""Catalog entries first sent by Tabbi (https://github.com/ethanwchen/tabbi at 60fef5f):
its requests that no other entry covers (tests/clients/tabbi/client.py)."""


import time

from clients.support import case, named

MULTI_READS = ["result[*].result", "result[*].error", "error"]

# A review at 2025-01-15 12:00 UTC, and the window start Tabbi sends (startID, ms).
PAST_REVIEW = 1736942400000

START_ID = 1735689600000

def subdecks(col, ctx):
    """The seeded card in Step1::Cardio, leaving Default empty (hidden from Anki's deck list)."""
    col.set_deck([ctx["cid"]], col.decks.id("Step1::Cardio"))

def review(col, cid, at_ms):
    col.db.execute("insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
                   "values (?, ?, -1, 3, 12, 5, 2500, 8000, 1)", at_ms, cid)

def reviewed_today(col, ctx):
    review(col, ctx["cid"], PAST_REVIEW)
    review(col, ctx["cid"], int(time.time() * 1000))

def reviewed_in_cardio(col, ctx):
    subdecks(col, ctx)
    review(col, ctx["cid"], PAST_REVIEW)


ENTRIES = named("Tabbi", [
    # The handshake (connect / checkAccess), then the summary refresh (AnkiSummary.swift summary()).
    case("deckNamesAndIds subdecks, Default empty", "deckNamesAndIds", setup=subdecks),
    case("multi getDeckStats deck by deck", "multi", {"actions": [
        {"action": "getDeckStats", "version": 6, "params": {"decks": [name]}}
        for name in ["Default", "Step1", "Step1::Cardio"]]}, reads=MULTI_READS, setup=subdecks),
    case("getNumCardsReviewedToday", "getNumCardsReviewedToday", setup=reviewed_today),
    case("getNumCardsReviewedByDay", "getNumCardsReviewedByDay",
         setup=lambda col, c: review(col, c["cid"], PAST_REVIEW)),
    # cardReviews skips child decks, so every deck is asked for in one multi.
    case("multi cardReviews every deck", "multi", {"actions": [
        {"action": "cardReviews", "version": 6, "params": {"deck": name, "startID": START_ID}}
        for name in ["Default", "Step1", "Step1::Cardio"]]},
        reads=["result[*].result", "result[*].error", "error"], setup=reviewed_in_cardio),
])
