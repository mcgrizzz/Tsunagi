"""JL: Japanese pop-up dictionary (Windows), mining to Anki through AnkiConnect."""

CLIENT = {
    "name": "JL",
    "repo": "https://github.com/rampaa/JL",
    "commit": "8995ac5",
    "read": "2026-10-15",
    "files": [
        "JL.Core/External/AnkiConnect/AnkiConnectClient.cs",
        "JL.Core/External/AnkiConnect/AnkiConnectUtils.cs",
        "JL.Core/External/AnkiConnect/AnkiConfigUtils.cs",
        "JL.Core/External/AnkiConnect/Note.cs",
        "JL.Core/External/AnkiConnect/Request.cs",
        "JL.Core/External/AnkiConnect/RequestWithParameters.cs",
        "JL.Core/External/AnkiConnect/Response.cs",
        "JL.Core/Mining/MiningUtils.cs",
        "JL.Core/Config/CoreConfigManager.cs",
    ],
    "uses": "System.Text.Json, version 6, null properties left out (no params, tags or media when unset); "
            "byte[] media data is sent as base64",
    "notes": "A non-null error string is shown verbatim and the result dropped; a non-2xx status is "
             "dropped silently. addNote's result is read with GetInt64. sync and guiBrowse aren't covered.",
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
                    "options": {
                        "allowDuplicate": False,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False},
                    },
                    "tags": [str],
                },
            },
            {
                "note": {
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {
                        "allowDuplicate": True,
                        "duplicateScope": "collection",
                        "duplicateScopeOptions": {"checkAllModels": True, "checkChildren": True},
                    },
                    "tags": [str],
                },
            },
            {
                "note": {
                    "audio": [{"data": str, "fields": [str], "filename": str, "skipHash": str}],
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {
                        "allowDuplicate": False,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False},
                    },
                    "tags": [str],
                },
            },
            {
                "note": {
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {
                        "allowDuplicate": False,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False},
                    },
                    "picture": [
                        {"data": str, "fields": [str], "filename": str},
                        {"fields": [str], "filename": str, "path": str},
                    ],
                    "tags": [str],
                },
            },
        ],
        ("result", "error"),
    ),
    "canAddNotes": (
        [
            {
                "notes": [
                    {
                        "deckName": str,
                        "fields": {str: str},
                        "modelName": str,
                        "options": {
                            "allowDuplicate": False,
                            "duplicateScope": "deck",
                            "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False},
                        },
                    },
                ],
            },
            {
                "notes": [
                    {
                        "deckName": str,
                        "fields": {str: str},
                        "modelName": str,
                        "options": {
                            "allowDuplicate": False,
                            "duplicateScope": "collection",
                            "duplicateScopeOptions": {"checkAllModels": True, "checkChildren": True},
                        },
                    },
                ],
            },
        ],
        ("result", "error"),
    ),
    "deckNames": ([{}], ("result", "error")),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelNames": ([{}], ("result", "error")),
}
