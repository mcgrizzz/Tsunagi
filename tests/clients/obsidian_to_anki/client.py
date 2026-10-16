"""Obsidian_to_Anki: the Obsidian plugin (TypeScript) and its command-line script (Python).

Both send every request with version 6 and params always present ({} when
empty), and both throw unless an answer has exactly two keys, result and
error, at every level of a nested multi (anki.ts invoke/parse,
obsidian_to_anki.py AnkiConnect.parse), so most cases read the whole answer.
"""

from clients.support import NOTE

CLIENT = {
    "name": "Obsidian_to_Anki",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Syncs Obsidian notes to Anki (plugin and script)",
    "repo": "https://github.com/ObsidianToAnki/Obsidian_to_Anki",
    "commit": "feb3db2",
    "read": "2026-10-15",
    "files": [
        "src/anki.ts",
        "src/files-manager.ts",
        "src/file.ts",
        "src/note.ts",
        "src/setting-to-data.ts",
        "main.ts",
        "obsidian_to_anki.py",
    ],
    "notes": ("No requestPermission, no key; README asks users to allow app://obsidian.md. "
              "Plugin media goes by local path (storeMediaFile {filename, path}); the script "
              "sends base64 data. New notes without a FILE TAGS line get the tag ''."),
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}

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
                    "options": {"allowDuplicate": False, "duplicateScope": "deck"},
                    "tags": [str, ""],
                },
            },
            {"note": {**NOTE, "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
            {
                "note": {
                    "audio": [],
                    "deckName": str,
                    "fields": {str: str},
                    "modelName": str,
                    "options": {"allowDuplicate": False, "duplicateScope": "deck"},
                    "tags": [str, ""],
                },
            },
        ],
        (),
    ),
    "addTags": ([{"notes": [int], "tags": str}], ()),
    "changeDeck": ([{"cards": [int], "deck": str}, {"cards": [], "deck": str}], ()),
    "createDeck": ([{"deck": str}], ()),
    "deleteNotes": ([{"notes": []}, {"notes": [int]}], ()),
    "findNotes": ([{"query": ""}], ("",)),
    "getTags": ([{}], ()),
    "modelFieldNames": ([{"modelName": str}], ("",)),
    "modelNames": ([{}], ("",)),
    "multi": (
        [
            {"actions": [{"action": "multi", "version": int}, {"action": "getTags", "version": int}]},
            {"actions": [{"action": "multi", "version": int}]},
            {"actions": [{"action": "createDeck", "version": int}]},
            {"actions": []},
            {"actions": [{"action": "addNote", "version": int}]},
            {"actions": [{"action": "notesInfo", "version": int}]},
            {"actions": [{"action": "deleteNotes", "version": int}]},
            {"actions": [{"action": "storeMediaFile", "version": int}]},
            {"actions": [{"action": "updateNoteFields", "version": int}]},
            {"actions": [{"action": "changeDeck", "version": int}]},
            {"actions": [{"action": "removeTags", "version": int}]},
            {"actions": [{"action": "addTags", "version": int}]},
            {"actions": [{"action": "modelFieldNames", "version": int}]},
        ],
        ("",),
    ),
    "notesInfo": ([{"notes": []}, {"notes": [int]}], ()),
    "removeTags": ([{"notes": [int], "tags": str}, {"notes": [], "tags": str}], ()),
    "storeMediaFile": ([{"filename": str, "path": str}, {"data": str, "filename": str}], ()),
    "updateNoteFields": (
        [
            {"note": {"fields": {str: str}, "id": int}},
            {"note": {"audio": [], "fields": {str: str}, "id": int}},
        ],
        (),
    ),
}
