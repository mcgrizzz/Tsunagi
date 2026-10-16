"""Jiten (jiten.moe): imports known words, review history and card media from Anki."""
from clients.support import case

CLIENT = {
    "name": "Jiten",
    "repo": "https://github.com/Sirush/Jiten",
    "commit": "fe383fc",
    "read": "2026-10-15",
    "files": [
        "Jiten.Web/app/components/AnkiConnectImport.vue",
        "Jiten.Web/app/composables/useAnkiMediaImport.ts",
        "Jiten.Web/app/utils/ankiMediaExtract.ts",
    ],
    "uses": ("its own ankiInvoke (version 6, params always sent, {} when empty) and yanki-connect 3.2.4 "
             "(3efb97b, src/client.ts: version 6, params left out when undefined) for deckNamesAndIds, "
             "findCards and the cardsInfo fallback"),
    "notes": ("A website (https://jiten.moe) calling http://127.0.0.1:8765 from the browser. cardsInfo with "
              "a fields filter is probed with cards: [] and, if it fails, plain cardsInfo is used. "
              "getReviewsOfCards is probed with cards: []. findCards runs once per deck the user opens "
              "(each step-2 load), cardsInfo once per 500 or 2000 cards, multi retrieveMediaFile in batches."),
}

FIELDS = ["cardId", "due", "queue", "type", "interval", "factor", "reps", "lapses", "mod", "flags",
          "fields", "modelName", "deckName"]
# What buildCardPayload and the field preview read of each card. It also reads mod (the last
# review when there is no history), a time that differs between runs, so it isn't compared.
CARD_READS = [f"result[*].{k}" for k in
              ["cardId", "queue", "fields", "interval", "factor", "due", "reps", "lapses"]] + ["error"]


def as_review(col, ctx):
    """The seeded card as a review card due in 3 days, so the import keeps it."""
    col.sched.set_due_date([ctx["cid"]], "3")


def in_subdeck(col, ctx):
    col.set_deck([ctx["cid"]], col.decks.id("日本語::Core_2k"))


def reviewed(col, ctx):
    col.db.execute("insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
                   "values (1736942400000, ?, -1, 3, 4, 1, 2500, 6000, 1)", ctx["cid"])



# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}
USES = [
    "cardsInfo new card",
    "deckNamesAndIds",
    "retrieveMediaFile",
    "version",
]

CASES = [
    # Connect: decks (yanki-connect), then the two capability probes (ankiInvoke).
    case("cardsInfo fields filter probe", "cardsInfo", {"cards": [], "fields": FIELDS},
         differs=("The Shim takes cardsInfo's fields, which AnkiConnect added after the pin "
                  "(0a5be02, 6.140): the probe passes, and Jiten reads in 2000-card chunks",
                  {"result": [], "error": None})),
    case("getReviewsOfCards probe", "getReviewsOfCards", {"cards": []}),
    # Step 2: the deck's cards (recursive deck: search, " * _ \\ escaped), then a 20-card preview.
    # AnkiConnect at the pinned commit fails the fields probe, so Jiten sends plain cardsInfo there.
    case("findCards deck", "findCards", {"query": 'deck:"Default"'}),
    case("findCards parent deck takes subdecks", "findCards", {"query": 'deck:"日本語"'}, setup=in_subdeck),
    case("findCards escaped underscore", "findCards", {"query": 'deck:"日本語::Core\\_2k"'}, setup=in_subdeck),
    case("cardsInfo fallback", "cardsInfo", lambda c: {"cards": [c["cid"]]}, reads=CARD_READS, setup=as_review),
    # Step 4: review history per chunk of card ids (numbers), keyed by card id.
    case("getReviewsOfCards", "getReviewsOfCards", lambda c: {"cards": [c["cid"]]}, setup=reviewed),
    # Media: batches through multi (versioned inner actions), a single file for previews,
    # and version as a liveness probe after a transport failure.
    case("multi retrieveMediaFile", "multi", {"actions": [
        {"action": "retrieveMediaFile", "version": 6, "params": {"filename": name}}
        for name in ["seed-1.txt", "missing.png"]]}),
    case("retrieveMediaFile missing", "retrieveMediaFile", {"filename": "missing.png"}),
]
