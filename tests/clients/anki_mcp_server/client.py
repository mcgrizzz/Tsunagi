"""anki-mcp-server: an MCP server giving AI assistants Anki tools, each one or more AnkiConnect actions."""

from clients.support import NOTE

CLIENT = {
    "name": "anki-mcp-server",
    "repo": "https://github.com/ankimcp/anki-mcp-server",
    "commit": "e0e347f",
    "read": "2026-10-15",
    "files": [
        "src/mcp/clients/anki-connect.client.ts",
        "src/mcp/utils/card-validation.utils.ts",
        "src/mcp/utils/card-suspension.utils.ts",
        "src/mcp/utils/card-states.utils.ts",
        "src/mcp/utils/anki.utils.ts",
        "src/mcp/primitives/essential/tools/",
        "src/mcp/primitives/gui/tools/",
    ],
    "uses": "ky; version 6 (ANKI_CONNECT_API_VERSION), params left out when the tool passes none "
            "(JSON.stringify drops undefined), one request at a time behind a global mutex",
    "notes": "A truthy error throws 'AnkiConnect error: <error>'; tools then match its text "
             "(duplicate, model, deck, field, not found, query, already exists). {} and null mark "
             "missing cards. HTTP 403 means a key problem; POST is retried on 408/413/429/5xx.",
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {"note": {"deckName": str, "fields": {str: str}, "modelName": str}},
            {
                "note": {
                    **NOTE,
                    "options": {
                        "allowDuplicate": False,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": str},
                    },
                },
            },
            {
                "note": {
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {"allowDuplicate": False, "duplicateScope": "deck"},
                },
            },
            {
                "note": {
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {"allowDuplicate": True},
                },
            },
        ],
        ("result", "error"),
    ),
    "addTags": ([{"notes": [int], "tags": str}], ("error",)),
    "answerCards": ([{"answers": [{"cardId": int, "ease": int}]}], ("result", "error")),
    "areSuspended": ([{"cards": [int]}], ("result", "error")),
    "cardReviews": ([{"deck": str, "startID": int}], ("result", "error")),
    "cardsInfo": (
        [{"cards": [int]}],
        ("result[*].cardId", "error", "result[*].question", "result[*].answer", "result[*].deckName", "result[*].modelName", "result[*].due", "result[*].interval", "result[*].factor", "result[*].reps", "result[*].lapses", "result[*].type", "result[*].note"),
    ),
    "cardsModTime": ([{"cards": [int]}], ("result[*].cardId", "error")),
    "changeDeck": ([{"cards": [int], "deck": str}], ("result", "error")),
    "clearUnusedTags": ([{}], ("error",)),
    "createDeck": ([{"deck": str}], ("result", "error")),
    "createModel": (
        [
            {
                "cardTemplates": [{"Back": str, "Front": str, "Name": str}],
                "inOrderFields": [str],
                "isCloze": False,
                "modelName": str,
            },
        ],
        ("result.id", "result.name", "error", "result"),
    ),
    "deckNames": ([{}], ("result", "error")),
    "deckNamesAndIds": ([{}], ("result", "error")),
    "deleteMediaFile": ([{"filename": str}], ("error",)),
    "deleteNotes": ([{"notes": [int]}], ("error",)),
    "findCards": ([{"query": str}], ("result", "error")),
    "findNotes": ([{"query": str}], ("result", "error")),
    "forgetCards": ([{"cards": [int]}], ("error",)),
    "getDeckStats": (
        [{"decks": [str]}],
        ("result.*.deck_id", "result.*.total_in_deck", "result.*.new_count", "result.*.learn_count", "result.*.review_count", "error", "result"),
    ),
    "getEaseFactors": ([{"cards": [int]}], ("result", "error")),
    "getIntervals": ([{"cards": [int]}], ("result", "error")),
    "getMediaFilesNames": ([{}, {"pattern": str}], ("result", "error")),
    "getReviewsOfCards": ([{"cards": [int]}], ("result", "error")),
    "getTags": ([{}], ("result", "error")),
    "modelFieldAdd": (
        [{"fieldName": str, "modelName": str}, {"fieldName": str, "index": int, "modelName": str}],
        ("error",),
    ),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelFieldRemove": ([{"fieldName": str, "modelName": str}], ("error",)),
    "modelFieldRename": ([{"modelName": str, "newFieldName": str, "oldFieldName": str}], ("error",)),
    "modelFieldReposition": ([{"fieldName": str, "index": int, "modelName": str}], ("error",)),
    "modelNames": ([{}], ("result", "error")),
    "modelStyling": ([{"modelName": str}], ("result.css", "error")),
    "modelTemplates": ([{"modelName": str}], ("result", "error")),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].modelName", "result[*].tags", "result[*].fields", "result[*].cards", "error"),
    ),
    "removeTags": ([{"notes": [int], "tags": str}], ("error",)),
    "replaceTags": ([{"notes": [int], "replace_with_tag": str, "tag_to_replace": str}], ("error",)),
    "retrieveMediaFile": ([{"filename": str}], ("result", "error")),
    "setDueDate": ([{"cards": [int], "days": str}], ("error",)),
    "storeMediaFile": (
        [
            {"data": str, "deleteExisting": True, "filename": str},
            {"deleteExisting": True, "filename": str, "path": str},
        ],
        ("result", "error"),
    ),
    "suspend": ([{"cards": [int]}], ("error",)),
    "unsuspend": ([{"cards": [int]}], ("error",)),
    "updateModelStyling": ([{"model": {"css": str, "name": str}}], ("error",)),
    "updateModelTemplates": (
        [{"model": {"name": str, "templates": {str: {"Back": str, "Front": str}}}}],
        ("error",),
    ),
    "updateNoteFields": ([{"note": {"fields": {str: str}, "id": int}}], ("error",)),
}
