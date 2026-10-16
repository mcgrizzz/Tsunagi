"""Yomitan: pop-up dictionary browser extension; mines lookups into Anki notes.

Every call goes through ext/js/comm/anki-connect.js `_invoke`: POST
{action, params, version: 2}, params always present ({} when empty), `key`
only when one is set. Version 2 means bare results: an answer that is an
object with an `error` property (even null) is taken as an error, so each
case reads the whole answer unless only some fields of rows are read.
"""

from clients.support import NOTE

CLIENT = {
    "name": "Yomitan",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Pop-up dictionary extension; mines words",
    "repo": "https://github.com/yomidevs/yomitan",
    "commit": "e7334a9",
    "read": "2026-10-15",
    "files": [
        "ext/js/comm/anki-connect.js",
        "ext/js/background/backend.js",
        "ext/js/data/anki-note-builder.js",
        "ext/js/data/anki-util.js",
        "ext/js/display/display-anki.js",
        "ext/js/pages/settings/anki-controller.js",
        "ext/js/pages/settings/anki-deck-generator-controller.js",
    ],
    "uses": "fetch, mode cors, credentials omit, Content-Type application/json; `multi` sub-actions carry no version",
    "notes": "Non-2xx is 'Anki connection error'; duplicates found by the substring "
             "'cannot create note because it is a duplicate'; falls back to canAddNotes on "
             "'Anki error: unsupported action'. Not tested: guiEditNote, guiBrowse, sync.",
}

ENVELOPE = {"version": 2, "params": "always", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {
                "note": {
                    **NOTE,
                    "options": {
                        "allowDuplicate": True,
                        "duplicateScope": "collection",
                        "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": None},
                    },
                },
            },
            {
                "note": {
                    **NOTE,
                    "options": {
                        "allowDuplicate": True,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": True, "deckName": str},
                    },
                },
            },
        ],
        ("result", "error"),
    ),
    "addNotes": (
        [
            {
                "notes": [
                    {
                        **NOTE,
                        "options": {
                            "allowDuplicate": True,
                            "duplicateScope": "collection",
                            "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": None},
                        },
                    },
                ],
            },
            {
                "notes": [
                    {
                        **NOTE,
                        "options": {
                            "allowDuplicate": True,
                            "duplicateScope": "collection",
                            "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": None},
                        },
                    },
                    {
                        "deckName": str,
                        "fields": {str: (str, "")},
                        "modelName": str,
                        "options": {
                            "allowDuplicate": True,
                            "duplicateScope": "collection",
                            "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": None},
                        },
                        "tags": [str],
                    },
                ],
            },
        ],
        ("result", "error"),
    ),
    "canAddNotes": (
        [
            {
                "notes": [
                    {
                        **NOTE,
                        "options": {
                            "allowDuplicate": True,
                            "duplicateScope": "collection",
                            "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": None},
                        },
                    },
                    {
                        **NOTE,
                        "options": {
                            "allowDuplicate": False,
                            "duplicateScope": "collection",
                            "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": None},
                        },
                    },
                ],
            },
        ],
        ("result", "error"),
    ),
    "canAddNotesWithErrorDetail": (
        [
            {
                "notes": [
                    {
                        **NOTE,
                        "options": {
                            "allowDuplicate": False,
                            "duplicateScope": "collection",
                            "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": None},
                        },
                    },
                    {
                        "deckName": str,
                        "fields": {str: ""},
                        "modelName": str,
                        "options": {
                            "allowDuplicate": False,
                            "duplicateScope": "collection",
                            "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": None},
                        },
                        "tags": [str],
                    },
                ],
            },
            {
                "notes": [
                    {
                        **NOTE,
                        "options": {
                            "allowDuplicate": False,
                            "duplicateScope": "deck",
                            "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": True, "deckName": str},
                        },
                    },
                ],
            },
            {
                "notes": [
                    {
                        **NOTE,
                        "options": {
                            "allowDuplicate": False,
                            "duplicateScope": "collection",
                            "duplicateScopeOptions": {"checkAllModels": True, "checkChildren": False, "deckName": None},
                        },
                    },
                ],
            },
        ],
        ("result", "error"),
    ),
    "cardsInfo": (
        [{"cards": [int]}, {"cards": []}],
        ("result[*].cardId", "result[*].note", "result[*].flags", "result[*].queue", "error", "result"),
    ),
    "deckNames": ([{}], ("result", "error")),
    "findCards": ([{"query": str}], ("result", "error")),
    "findNotes": ([{"query": str}, {"query": ""}], ("result", "error")),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelNames": ([{}], ("result", "error")),
    "multi": ([{"actions": [{"action": "findNotes"}]}], ("result", "error")),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].modelName", "result[*].fields.*.value", "result[*].fields.*.order", "result[*].tags", "result[*].cards", "error", "result"),
    ),
    "storeMediaFile": ([{"data": str, "filename": str}], ("result", "error")),
    "suspend": ([{"cards": [int]}], ("result", "error")),
    "updateNoteFields": (
        [
            {
                "note": {
                    **NOTE,
                    "id": int,
                    "options": {
                        "allowDuplicate": True,
                        "duplicateScope": "collection",
                        "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": None},
                    },
                },
            },
        ],
        ("result", "error"),
    ),
    "version": ([{}], ("result", "error")),
}
