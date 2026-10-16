"""Jiten (jiten.moe): imports known words, review history and card media from Anki."""

CLIENT = {
    "name": "Jiten",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Imports known words and review history (jiten.moe)",
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

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "cardsInfo": (
        [{"cards": [], "fields": [str]}, {"cards": [int]}],
        ("result", "error", "result[*].cardId", "result[*].queue", "result[*].fields", "result[*].interval", "result[*].factor", "result[*].due", "result[*].reps", "result[*].lapses"),
    ),
    "deckNamesAndIds": ([{}], ("result", "error")),
    "findCards": ([{"query": str}], ("result", "error")),
    "getReviewsOfCards": ([{"cards": []}, {"cards": [int]}], ("result", "error")),
    "multi": (
        [{"actions": [{"action": "retrieveMediaFile", "version": int}]}],
        ("result", "error"),
    ),
    "retrieveMediaFile": ([{"filename": str}], ("result", "error")),
    "version": ([{}], ("result", "error")),
}

# Deliberate differences from AnkiConnect this client sees, accepted (support.py).
ACCEPTS = {
    "cardsInfo fields filter probe (Jiten)":
        "The Shim takes cardsInfo's fields, which AnkiConnect added after the pin (0a5be02, 6.140): the probe passes, and Jiten reads in 2000-card chunks",
}
