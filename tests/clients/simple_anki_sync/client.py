"""simple-anki-sync: Obsidian plugin syncing Markdown tables to Anki, one request at a time.

sendRequest (anki-service.ts) sends version 6 with params always present ({}
when empty) and rejects an answer without both result and error keys, or
with a non-null error. Since PR #4 (2026-10-12) it sends card ids, read from
notesInfo, to cardsInfo and changeDeck.
"""

from clients.support import NOTE

CLIENT = {
    "name": "simple-anki-sync",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Syncs Markdown tables in Obsidian to Anki",
    "repo": "https://github.com/russluber/simple-anki-sync",
    "commit": "36ddadd",
    "read": "2026-10-15",
    "files": [
        "src/anki-service.ts",
        "src/main.ts",
        "src/settings.ts",
        "src/deck-name.ts",
    ],
    "notes": ("Before PR #4 (7e84eed) it sent the note id as a card id to cardsInfo and "
              "changeDeck and read cardsInfo[0].deckName. No key."),
}

# XMLHttpRequest.send of a string with no Content-Type: text/plain;charset=UTF-8.
ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST", "content_type": "text"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {"note": NOTE},
            {"note": {"deckName": str, "fields": {str: (str, "")}, "modelName": str, "tags": [str]}},
        ],
        ("result", "error"),
    ),
    "cardsInfo": ([{"cards": [int]}], ("result[*].cardId", "result[*].deckName", "error")),
    "changeDeck": ([{"cards": [int], "deck": str}], ("result", "error")),
    "createDeck": ([{"deck": str}], ("error",)),
    "deckNames": ([{}], ("result", "error")),
    "deleteNotes": ([{"notes": [int]}], ("error",)),
    "modelNames": ([{}], ("result", "error")),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].cards", "result[*].tags", "error"),
    ),
    "requestPermission": ([{}], ("result.permission", "error")),
    "storeMediaFile": ([{"data": str, "filename": str}], ("error",)),
    "updateNoteFields": ([{"note": {"fields": {str: str}, "id": int}}], ("result", "error")),
    "updateNoteTags": ([{"note": int, "tags": [str]}], ("result", "error")),
}
