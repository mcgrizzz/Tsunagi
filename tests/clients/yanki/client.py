"""Yanki: Markdown to Anki sync (CLI, and yanki-obsidian), through yanki-connect."""

from clients.support import NOTE

CLIENT = {
    "name": "Yanki",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Syncs Markdown to Anki (command line and Obsidian)",
    "needs": ("0.7.5", "to delete a deck and its subdecks in one sync"),
    "repo": "https://github.com/kitschpatrol/yanki",
    "commit": "60603b4",
    "read": "2026-10-15",
    "files": [
        "src/lib/utilities/anki-connect.ts",
        "src/lib/model/model.ts",
    ],
    "uses": "yanki-connect 2a2bd21 (src/client.ts): version 6, params left out when empty, every call one at a time",
    "notes": "Matches error messages exactly; needs HTTP 200.",
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": ([{"note": {**NOTE, "options": {"allowDuplicate": True}}}], ("result", "error")),
    "changeDeck": ([{"cards": [int], "deck": str}], ("result", "error")),
    "createDeck": ([{"deck": str}], ("error",)),
    "createModel": (
        [
            {
                "cardTemplates": [{"Back": str, "Front": str, "YankiNamespace": str}],
                "inOrderFields": [str],
                "modelName": str,
            },
        ],
        ("error", "result"),
    ),
    "deckNames": ([{}], ("result", "error")),
    "deleteDecks": (
        [{"cardsToo": True, "decks": []}, {"cardsToo": True, "decks": [str]}],
        ("result", "error"),
    ),
    "deleteMediaFile": ([{"filename": str}], ("result", "error")),
    "deleteNotes": ([{"notes": []}], ("result", "error")),
    "findNotes": ([{"query": str}], ("result", "error")),
    "getDeckConfig": ([{"deck": str}], ("result.dyn", "error", "result")),
    "getDeckStats": (
        [{"decks": [str]}],
        ("result.*.total_in_deck", "result.*.new_count", "result.*.learn_count", "result.*.review_count", "error"),
    ),
    "getDecks": ([{"cards": [int]}], ("result", "error")),
    "getMediaFilesNames": ([{"pattern": str}], ("result", "error")),
    "modelStyling": ([{"modelName": str}], ("result.css", "error", "result")),
    "notesInfo": ([{"notes": [int]}], ("result", "error")),
    "requestPermission": ([{}], ("result.permission", "error")),
    "storeMediaFile": ([{"data": str, "deleteExisting": True, "filename": str}], ("result", "error")),
    "updateModelStyling": ([{"model": {"css": str, "name": str}}], ("result", "error")),
    "updateNoteModel": (
        [
            {"note": {**NOTE, "cards": [int], "id": int, "noteId": int}},
            {"note": {"fields": {str: str}, "id": int, "modelName": str, "tags": []}},
        ],
        ("result", "error"),
    ),
}
