"""logseq-anki-sync: syncs Logseq blocks (cloze, multiline, image occlusion) to Anki notes."""

from clients.support import NOTE

CLIENT = {
    "name": "logseq-anki-sync",
    "repo": "https://github.com/debanjandhar12/logseq-anki-sync",
    "commit": "0d881e3",
    "read": "2026-10-15",
    "files": [
        "src/anki-connect/AnkiConnect.ts",
        "src/anki-connect/internal/AnkiActionQueue.ts",
        "src/anki-connect/internal/AnkiNoteCache.ts",
        "src/anki-connect/operations/AddNoteOperation.ts",
        "src/anki-connect/operations/UpdateNoteOperation.ts",
        "src/anki-connect/operations/DeleteNoteOperation.ts",
        "src/anki-connect/operations/AssetOperation.ts",
        "src/sync/syncLogseqToAnki.ts",
        "src/sync/tasks/SuspendUnsuspendNotesTask.ts",
        "src/addons/PreviewInAnki.ts",
    ],
    "uses": ("invoke(): XMLHttpRequest POST, version 6, params always sent ({} when empty); "
             "multi inner actions carry no version (so AnkiConnect answers them as version 4, bare)"),
    "notes": ("Rejects a reply that doesn't have exactly two keys, error and result, and throws on a "
              "truthy error. Matches updateModelTemplates's error text exactly. Writes go through multi "
              "in batches of 128. guiBrowse and exportPackage (createBackup, a relative path) are not tested."),
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": ([{"note": {**NOTE, "options": {"allowDuplicate": True}}}], ()),
    "addTags": ([{"notes": [int], "tags": str}], ()),
    "changeDeck": ([{"cards": [int], "deck": str}], ()),
    "createDeck": ([{"deck": str}], ()),
    "createModel": (
        [
            {
                "cardTemplates": [{"Back": str, "Front": str, "Name": str}],
                "css": "",
                "inOrderFields": [str],
                "isCloze": True,
                "modelName": str,
            },
        ],
        ("error",),
    ),
    "deckNames": ([{}], ("",)),
    "deleteNotes": ([{"notes": [int]}], ()),
    "findNotes": ([{"query": str}], ("",)),
    "getDecks": ([{"cards": [int]}, {"cards": []}], ("",)),
    "getMediaFilesNames": ([{}], ("",)),
    "modelFieldAdd": ([{"fieldName": str, "modelName": str}], ("",)),
    "modelFieldNames": ([{"modelName": str}], ("",)),
    "modelFieldRemove": ([{"fieldName": str, "modelName": str}], ("",)),
    "modelFieldReposition": ([{"fieldName": str, "index": int, "modelName": str}], ("",)),
    "modelNames": ([{}], ("",)),
    "multi": (
        [
            {"actions": [{"action": "retrieveMediaFile"}]},
            {"actions": [{"action": "storeMediaFile"}]},
            {"actions": []},
            {"actions": [{"action": "createDeck"}, {"action": "addNote"}]},
            {"actions": [{"action": "findNotes"}]},
            {"actions": [{"action": "updateNoteFields"}]},
            {
                "actions": [
                    {"action": "changeDeck"},
                    {"action": "removeTags"},
                    {"action": "addTags"},
                    {"action": "updateNoteFields"},
                ],
            },
            {"actions": [{"action": "deleteNotes"}]},
        ],
        ("",),
    ),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].cards", "result[*].fields", "result[*].tags", "error"),
    ),
    "reloadCollection": ([{}], ("",)),
    "removeTags": ([{"notes": [int], "tags": str}], ()),
    "requestPermission": ([{}], ("result.permission", "error")),
    "retrieveMediaFile": ([{"filename": str}], ()),
    "storeMediaFile": ([{"data": str, "filename": str}], ()),
    "suspend": ([{"cards": [int]}], ("",)),
    "unsuspend": ([{"cards": [int]}], ("",)),
    "updateModelTemplates": (
        [{"model": {"name": str, "templates": {str: {"Back": str, "Front": str}}}}],
        ("",),
    ),
    "updateNoteFields": (
        [{"note": {"deckName": str, "fields": {str: str}, "id": int, "modelName": str}}],
        (),
    ),
}
