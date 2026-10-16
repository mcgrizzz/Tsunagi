"""Yomine: a Japanese immersion miner; its AnkiConnect path (used when GET /v1/health isn't Tsunagi's)."""

CLIENT = {
    "name": "Yomine",
    "repo": "https://github.com/mcgrizzz/Yomine",
    "commit": "7044efc",
    "read": "2026-10-15",
    "files": [
        "src/anki/ankiconnect.rs",
        "src/anki/client.rs",
        "src/anki/sync.rs",
        "src-tauri/src/commands/mining.rs",
        "src-tauri/src/commands/anki.rs",
        "src-tauri/src/batches.rs",
        "src-tauri/src/media.rs",
    ],
    "uses": "reqwest; version 6, params left out when None, key only when set; one new connection per request",
    "notes": "Reads result and error only, never the HTTP status. An error containing 'duplicate' is a "
             "duplicate; one containing deck, model, note type, api key or permission is a setup error.",
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {
                "note": {
                    "audio": [],
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {"allowDuplicate": False},
                    "picture": [],
                    "tags": [str],
                },
            },
            {
                "note": {
                    "audio": [{"data": str, "fields": [str], "filename": str}],
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {"allowDuplicate": False},
                    "picture": [{"data": str, "fields": [str], "filename": str}],
                    "tags": [str],
                },
            },
        ],
        ("result", "error"),
    ),
    "deleteNotes": ([{"notes": [int]}], ("error",)),
    "findNotes": ([{"query": str}], ("result", "error")),
    "getActiveProfile": ([{}], ("result", "error")),
    "getIntervals": ([{"cards": [int]}], ("result", "error")),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelNamesAndIds": ([{}], ("result", "error")),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].modelName", "result[*].fields.*.value", "result[*].cards", "error"),
    ),
    "retrieveMediaFile": ([{"filename": str}], ("result", "error")),
    "storeMediaFile": ([{"data": str, "filename": str}], ("result", "error")),
    "updateNoteFields": ([{"note": {"fields": {str: str}, "id": int}}], ("error",)),
    "version": ([{}], ("result", "error")),
}
