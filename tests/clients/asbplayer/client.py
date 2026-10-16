"""asbplayer: subtitle player (web app and extension) mining sentence cards, with an Anki word cache."""

from clients.support import NOTE

CLIENT = {
    "name": "asbplayer",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Subtitle player; mines sentence cards",
    "repo": "https://github.com/asbplayer/asbplayer",
    "commit": "62c4d6e",
    "read": "2026-10-15",
    "files": [
        "common/anki/anki.ts",
        "common/dictionary-db/dictionary-db-anki.ts",
        "common/annotations/anki-annotations.ts",
        "common/components/AnkiSettingsTab.tsx",
        "common/components/CardSelectView.tsx",
        "common/components/WordField.tsx",
        "common/src/fetcher.ts",
        "extension/src/handlers/video/http-post-handler.ts",
    ],
    "uses": "Anki._executeAction (anki.ts L865-889): version 6, key only if set, params left out when null; "
            "one POST per action, no multi; batches one after another",
    "notes": "Any error throws; an error containing 'duplicate' is a DuplicateNoteError. "
             "The extension proxies only 19 actions (http-post-handler.ts L5-25).",
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {
                "note": {
                    **NOTE,
                    "audio": {"data": str, "fields": [str], "filename": str},
                    "options": {
                        "allowDuplicate": True,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {"checkChildren": False, "deckName": str},
                    },
                    "picture": {"data": str, "fields": [str], "filename": str},
                },
            },
            {
                "note": {
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {
                        "allowDuplicate": True,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {"checkChildren": False, "deckName": str},
                    },
                    "tags": [],
                },
            },
        ],
        ("result", "error"),
    ),
    "addTags": ([{"notes": [int], "tags": str}], ("result", "error")),
    "areSuspended": ([{"cards": [int]}], ("result", "error")),
    "cardsInfo": (
        [{"cards": [int]}],
        ("result[*].cardId", "result[*].deckName", "result[*].modelName", "result[*].due", "error"),
    ),
    "cardsModTime": ([{"cards": [int]}], ("result[*].cardId", "error")),
    "createDeck": ([{"deck": str}], ("error",)),
    "createModel": (
        [
            {
                "cardTemplates": [{"Back": str, "Front": str}],
                "css": str,
                "inOrderFields": [str],
                "modelName": str,
            },
        ],
        ("error",),
    ),
    "deckNames": ([{}], ("result", "error")),
    "findCards": ([{"query": str}], ("result", "error")),
    "findNotes": ([{"query": str}], ("result", "error")),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelNames": ([{}], ("result", "error")),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].fields", "error", "result[*].tags", "result[*].cards", "result[*].modelName"),
    ),
    "notesModTime": ([{"notes": [int]}], ("result[*].noteId", "error")),
    "requestPermission": (
        [{}],
        ("result.permission", "result.requireApikey", "result.requireApiKey?", "error"),
    ),
    "storeMediaFile": ([{"data": str, "deleteExisting": False, "filename": str}], ("result", "error")),
    "updateNoteFields": (
        [
            {
                "note": {
                    **NOTE,
                    "id": int,
                    "options": {
                        "allowDuplicate": True,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {"checkChildren": False, "deckName": str},
                    },
                },
            },
            {"note": {"fields": {str: str}, "id": int}},
        ],
        ("result", "error"),
    ),
    "version": ([{}], ("result", "error")),
}
