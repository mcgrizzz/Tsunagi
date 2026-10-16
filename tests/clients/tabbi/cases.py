"""Tabbi: a macOS notch app whose Anki panel shows due counts, streaks and retention."""
import time

from clients.support import case

CLIENT = {
    "name": "Tabbi",
    "repo": "https://github.com/ethanwchen/tabbi",
    "commit": "60fef5f",
    "read": "2026-10-15",
    "files": [
        "Sources/TabbiKitCore/Anki/AnkiConnectClient.swift",
        "Sources/TabbiKitCore/Anki/AnkiConnectModels.swift",
        "Sources/TabbiKitCore/Anki/AnkiConnectError.swift",
        "Sources/TabbiKitCore/Anki/AnkiConnectTransport.swift",
        "Sources/TabbiKitCore/Anki/AnkiSummary.swift",
        "Sources/TabbiKitCore/Anki/AnkiDeckOpener.swift",
    ],
    "uses": "version 6; params and key left out when nil; multi inner actions carry version 6 (and the key when set)",
    "notes": ("Decodes every reply strictly (Codable): a missing key or a wrong type fails the call. "
              "getDeckStats replies are matched by deck_id. Since PR #131 a failed getDeckStats is asked "
              "again without Default, then deck by deck through multi. Errors are matched by text "
              "(api key, unsupported action, collection closed) and otherwise shown as Anki wrote them. "
              "guiDeckReview and sync are not tested."),
}

# Tabbi decodes all six keys of every deck entry (deck_id, name, new_count, learn_count,
# review_count, total_in_deck), which is the whole entry. The entries are keyed by deck id,
# which a "result.*.key" read would keep in its path, so the whole result is compared.
DECK_READS = ["result", "error"]
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



# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}
USES = [
    "deckNamesAndIds",
    "getDeckStats",
    "requestPermission",
]

CASES = [
    # The handshake (connect / checkAccess), then the summary refresh (AnkiSummary.swift summary()).
    case("deckNamesAndIds subdecks, Default empty", "deckNamesAndIds", setup=subdecks),
    # Every deck from deckNamesAndIds, sorted by name.
    case("getDeckStats empty Default and subdecks", "getDeckStats",
         {"decks": ["Default", "Step1", "Step1::Cardio"]}, reads=DECK_READS, setup=subdecks),
    # PR #131: the batch again without Default, then each deck on its own in one multi.
    case("getDeckStats without Default", "getDeckStats", {"decks": ["Step1", "Step1::Cardio"]},
         reads=DECK_READS, setup=subdecks),
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
]
