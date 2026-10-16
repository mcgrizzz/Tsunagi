"""Flashcards (Obsidian): an Obsidian plugin that syncs cards written in notes to Anki.

Every call goes through src/adapters/anki/anki-connect-client.ts `invoke`:
POST {action, version: 6, params} with params always present ({} when
empty) and `key` only when an API key secret is set, sent with Obsidian's
requestUrl (not fetch, so no CORS origin to allow). A non-2xx status or a
non-null `error` throws; otherwise `result` is returned. Media goes in one
`multi` of storeMediaFile whose sub-actions carry no version.
"""

from clients.support import NOTE

CLIENT = {
    "name": "Flashcards (Obsidian)",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Obsidian plugin; syncs cards from notes",
    "repo": "https://github.com/reuseman/flashcards-obsidian",
    "commit": "2ca53d0",
    "read": "2026-10-16",
    "files": [
        "src/adapters/anki/anki-connect-client.ts",
        "src/adapters/anki/upload-media.ts",
        "src/adapters/anki/manage-managed-model-style.ts",
        "src/adapters/anki/repair-managed-source-templates.ts",
        "src/adapters/obsidian/anki-availability.ts",
        "src/adapters/obsidian/anki-connect-transport.ts",
        "src/adapters/obsidian/delete-confirm-modal.ts",
        "src/application/sync/execute-sync-plan.ts",
        "src/application/sync/load-live-anki-state.ts",
        "src/application/sync/sync-execution-session.ts",
        "src/core/render/render-card.ts",
    ],
    "uses": "version 6; params always; key only when configured; multi sub-actions carry no version",
    "notes": ("version is the liveness probe (and can start Anki first). Makes its own note types "
              "(Obsidian-basic, -basic-reversed, -cloze, -reminder) with createModel, then adds the "
              "Context and Source fields with modelFieldAdd and rewrites templates. A note missing "
              "from notesInfo (no noteId) is added again. addNote sends no options, so AnkiConnect's "
              "duplicate check applies; the error is shown as the card's failure. A model change goes "
              "through updateNoteModel, then changeDeck with the refreshed card ids. Media "
              "storeMediaFile answers inside multi aren't read: a failed file goes unnoticed. "
              "Not tested: scripts/native (a developer harness: findNotes, findCards, deleteDecks, "
              "getActiveProfile, sync), not part of the plugin."),
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}

# Fields: Context is "" when the card has none, Source is always a link.
FIELDS = {str: (str, "")}
MODEL = {
    "cardTemplates": [{"Back": str, "Front": str, "Name": str}],
    "css": str,
    "inOrderFields": [str],
    "modelName": str,
}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {"note": {**NOTE, "fields": FIELDS}},
            {"note": NOTE},
            # No default tags and none in the note.
            {"note": {**NOTE, "fields": FIELDS, "tags": []}},
        ],
        ("result", "error"),
    ),
    "addTags": ([{"notes": [int], "tags": str}], ("error",)),
    "cardsInfo": ([{"cards": [int]}], ("result[*].cardId", "result[*].deckName", "error")),
    "changeDeck": ([{"cards": [int], "deck": str}], ("error",)),
    "createDeck": ([{"deck": str}], ("error",)),
    "createModel": ([{**MODEL, "isCloze": False}, {**MODEL, "isCloze": True}], ("error",)),
    "deckNames": ([{}], ("result", "error")),
    "deleteNotes": ([{"notes": [int]}], ("error",)),
    "modelFieldAdd": ([{"fieldName": str, "index": int, "modelName": str}], ("error",)),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelNames": ([{}], ("result", "error")),
    "modelStyling": ([{"modelName": str}], ("result.css", "error")),
    "modelTemplates": ([{"modelName": str}], ("result", "error")),
    "multi": ([{"actions": [{"action": "storeMediaFile"}]}], ("error",)),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].cards", "result[*].fields", "result[*].modelName",
         "result[*].tags", "error"),
    ),
    "removeTags": ([{"notes": [int], "tags": str}], ("error",)),
    "storeMediaFile": ([{"data": str, "filename": str}], ()),
    "updateModelStyling": ([{"model": {"css": str, "name": str}}], ("error",)),
    "updateModelTemplates": ([{"model": {"name": str, "templates": {str: {"Back": str, "Front": str}}}}],
                             ("error",)),
    "updateNoteFields": (
        [{"note": {"fields": FIELDS, "id": int}}, {"note": {"fields": {str: str}, "id": int}}],
        ("error",),
    ),
    "updateNoteModel": ([{"note": {"fields": FIELDS, "id": int, "modelName": str, "tags": [str]}}],
                        ("error",)),
    "version": ([{}], ("result", "error")),
}
