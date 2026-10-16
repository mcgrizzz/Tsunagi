"""Saladict: pop-up dictionary browser extension; syncs its notebook into Anki.

All calls go through `request` in the AnkiConnect sync service: an axios POST
of {key, version: 6, action, params}, with `key: null` when none is set and
`params: {}` when there are none. An answer without a `result` key is taken
as a too-old AnkiConnect, a truthy `error` is thrown, else `result` is used.
"""

CLIENT = {
    "name": "Saladict",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Pop-up dictionary extension; syncs its notebook",
    "repo": "https://github.com/crimx/ext-saladict",
    "commit": "7d93a65",
    "read": "2026-10-15",
    "files": [
        "src/background/sync-manager/services/ankiconnect/index.ts",
        "src/options/components/Entries/Notebook/sync-services/ankiconnect.tsx",
        "src/content/components/WordEditor/Notes.tsx",
    ],
    "uses": "axios, default branch dev",
    "notes": "Defaults: deck 'Saladict', note type 'Saladict Word', no tags. Not tested: sync "
             "(after adding, if 'syncServer' is on; errors ignored).",
}

ENVELOPE = {"version": 6, "params": "always", "key": "null", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {
                "note": {
                    "deckName": str,
                    "fields": {str: ("", str)},
                    "modelName": str,
                    "options": {"allowDuplicate": False, "duplicateScope": "deck"},
                    "tags": [],
                },
            },
        ],
        ("result", "error"),
    ),
    "createDeck": ([{"deck": str}], ("result", "error")),
    "createModel": (
        [
            {
                "cardTemplates": [{"Back": str, "Front": str, "Name": str}],
                "css": str,
                "inOrderFields": [str],
                "modelName": str,
            },
        ],
        ("error",),
    ),
    "deckNames": ([{}], ("result", "error")),
    "findNotes": ([{"query": str}], ("result", "error")),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelNames": ([{}], ("result", "error")),
    "updateModelTemplates": (
        [{"model": {"name": str, "templates": {str: {"Back": str, "Front": str}}}}],
        ("result", "error"),
    ),
    "updateNoteFields": ([{"note": {"fields": {str: ("", str)}, "id": int}}], ("result", "error")),
    "version": ([{}], ("result", "error")),
}
