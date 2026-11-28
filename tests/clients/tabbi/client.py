"""Tabbi: a macOS notch app whose Anki panel shows due counts, streaks and retention."""

CLIENT = {
    "name": "Tabbi",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "macOS notch app showing due counts and streaks",
    "repo": "https://github.com/ethanwchen/tabbi",
    "commit": "0c26aac",
    "read": "2026-11-28",
    "files": [
        "Sources/TabbiKitCore/Anki/AnkiConnectClient.swift",
        "Sources/TabbiKitCore/Anki/AnkiConnectModels.swift",
        "Sources/TabbiKitCore/Anki/AnkiConnectError.swift",
        "Sources/TabbiKitCore/Anki/AnkiConnectTransport.swift",
        "Sources/TabbiKitCore/Anki/AnkiSummary.swift",
        "Sources/TabbiKitCore/Anki/AnkiDeckOpener.swift",
        "windows/src/core/anki/ankiConnectClient.ts",
        "windows/src/core/anki/ankiConnectModels.ts",
        "windows/src/core/anki/ankiConnectError.ts",
        "windows/src/core/anki/ankiSummary.ts",
        "windows/src/modules/anki/ankiStore.ts",
    ],
    "uses": "version 6; params and key left out when nil; multi inner actions carry version 6 (and the key when set)",
    "notes": ("Decodes every reply strictly (Codable): a missing key or a wrong type fails the call. "
              "getDeckStats replies are matched by deck_id. Since PR #131 a failed getDeckStats is asked "
              "again without Default, then deck by deck through multi. Errors are matched by text "
              "(api key, unsupported action, collection closed) and otherwise shown as Anki wrote them. "
              "guiDeckReview and sync are not tested. The Windows app (windows/, TypeScript, since November 2026) "
              "is a port of the same client: the same actions, requests and strict reading."),
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "cardReviews": ([{"deck": str, "startID": int}], ()),
    "deckNamesAndIds": ([{}], ("result", "error")),
    "getDeckStats": ([{"decks": [str]}], ("result", "error")),
    "getNumCardsReviewedByDay": ([{}], ("result", "error")),
    "getNumCardsReviewedToday": ([{}], ("result", "error")),
    "multi": (
        [
            {"actions": [{"action": "getDeckStats", "version": int}]},
            {"actions": [{"action": "cardReviews", "version": int}]},
        ],
        ("result[*].result", "result[*].error", "error"),
    ),
    "requestPermission": (
        [{}],
        ("result.permission", "result.requireApikey", "result.requireApiKey?", "result.version", "error"),
    ),
}
