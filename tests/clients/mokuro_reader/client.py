"""mokuro-reader: manga reader (web app) making or updating Anki cards from a page crop."""

CLIENT = {
    "name": "mokuro-reader",
    "repo": "https://github.com/Gnathonic/mokuro-reader",
    "commit": "bfaeb48",
    "read": "2026-10-15",
    "files": [
        "src/lib/anki-connect/index.ts",
        "src/lib/components/Reader/TextBoxPicker.svelte",
        "src/lib/components/Reader/Reader.svelte",
        "src/lib/components/Reader/AnkiFieldModal.svelte",
    ],
    "uses": "ankiConnect / ankiConnectRaw (index.ts L294-309, L540-585): {action, params, version: 6}, "
            "params always sent ({} when empty), no key, no multi; version and requestPermission without params",
    "notes": "HTTP status ignored. An answer with an error fails; otherwise result is returned, and "
             "updateNoteFields fails when result is undefined (index.ts L1054-1059), so result must be "
             "present even when null. createDeck null means AnkiConnect Android (index.ts L264-274). "
             "Update accepts only a note younger than 5 minutes by its id (index.ts L608-610, L940; TextBoxPicker.svelte L125).",
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {
                "note": {
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {"allowDuplicate": True},
                    "picture": [{"data": str, "fields": [str], "filename": str}],
                    "tags": [str],
                },
            },
            {
                "note": {
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {"allowDuplicate": True},
                    "picture": [{"data": str, "fields": [str], "filename": str}],
                },
            },
        ],
        ("result", "error"),
    ),
    "addTags": ([{"notes": [int], "tags": str}], ("result", "error")),
    "createDeck": ([{"deck": str}], ("result", "error")),
    "deckNames": ([{}], ("result", "error")),
    "deleteDecks": ([{"cardsToo": True, "decks": [str]}], ("result", "error")),
    "findNotes": ([{"query": str}], ("result", "error")),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelNames": ([{}], ("result", "error")),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].modelName", "result[*].tags", "result[*].fields", "error"),
    ),
    "requestPermission": ([{}], ("result.permission",)),
    "updateNoteFields": (
        [
            {
                "note": {
                    "fields": {str: ("", str)},
                    "id": int,
                    "picture": [{"data": str, "fields": [str], "filename": str}],
                },
            },
            {
                "note": {
                    "fields": {str: str},
                    "id": int,
                    "picture": [{"data": str, "fields": [str], "filename": str}],
                },
            },
        ],
        ("result", "error"),
    ),
    "version": ([{}], ("result", "error")),
}
