"""Yanki: Markdown to Anki sync (CLI, and yanki-obsidian), through yanki-connect."""

from clients.support import NOTE

CLIENT = {
    "name": "Yanki",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Syncs Markdown to Anki (command line and Obsidian)",
    "repo": "https://github.com/kitschpatrol/yanki",
    "commit": "f8522b7",
    "read": "2026-11-25",
    "files": [
        "src/lib/utilities/anki-connect.ts",
        "src/lib/model/model.ts",
        "src/lib/actions/sync-notes.ts",
    ],
    "uses": "yanki-connect 5.3.1 (src/client.ts): version 6, params left out when empty, every call one at a time",
    "notes": "Matches error messages exactly; needs HTTP 200.",
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": ([{"note": {**NOTE, "options": {"allowDuplicate": True}}}], ("result", "error")),
    # sync-notes.ts: after changing a note type, any error here runs guiCheckDatabase (by hand) and this reload.
    "cardsInfo": ([{"cards": [int]}, {"cards": []}], ("error",)),
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
    "deckNamesAndIds": ([{}], ("result", "error")),
    "deleteDecks": ([{"cardsToo": True, "decks": [str]}], ("result", "error")),
    "deleteMediaFile": ([{"filename": str}], ("result", "error")),
    "deleteNotes": ([{"notes": []}], ("result", "error")),
    "findCards": ([{"query": str}], ("result", "error")),
    "findNotes": ([{"query": str}], ("result", "error")),
    "getDecks": ([{"cards": [int]}], ("result", "error")),
    "getMediaFilesNames": ([{"pattern": str}], ("result", "error")),
    "modelStyling": ([{"modelName": str}], ("result.css", "error", "result")),
    "notesInfo": ([{"notes": [int]}], ("result", "error")),
    "reloadCollection": ([{}], ("error",)),
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
