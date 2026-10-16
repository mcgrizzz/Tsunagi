"""Catalog entries first sent by Jiten (https://github.com/Sirush/Jiten at fe383fc):
its requests that no other entry covers (tests/clients/jiten/client.py)."""


from clients.support import case, named

FIELDS = ["cardId", "due", "queue", "type", "interval", "factor", "reps", "lapses", "mod", "flags",
          "fields", "modelName", "deckName"]


ENTRIES = named("Jiten", [
    # Connect: decks (yanki-connect), then the two capability probes (ankiInvoke).
    case("cardsInfo fields filter probe", "cardsInfo", {"cards": [], "fields": FIELDS},
         differs=("The Shim takes cardsInfo's fields, which AnkiConnect added after the pin "
                  "(0a5be02, 6.140): the probe passes, and Jiten reads in 2000-card chunks",
                  {"result": [], "error": None})),
    case("getReviewsOfCards probe", "getReviewsOfCards", {"cards": []}),
    # Media: batches through multi (versioned inner actions), a single file for previews,
    # and version as a liveness probe after a transport failure.
    case("multi retrieveMediaFile", "multi", {"actions": [
        {"action": "retrieveMediaFile", "version": 6, "params": {"filename": name}}
        for name in ["seed-1.txt", "missing.png"]]}),
])
