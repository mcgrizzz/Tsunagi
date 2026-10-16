"""Raycast Anki: the Anki extension for the Raycast launcher (macOS); browses, studies and adds notes.

Every call goes through extensions/anki/src/api/ankiClient.ts `ankiReq`: axios
POST {action, version: 6, params} (params {} when there are none) to
127.0.0.1:<port>, a 2 s timeout, no key. An answer with a truthy `error`
throws it as Anki wrote it; otherwise `result` is returned. The AI tools
(src/tools) send the same requests.
"""

from clients.support import NOTE

CLIENT = {
    "name": "Raycast Anki",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Anki extension for the Raycast launcher (macOS); browses, studies and adds notes",
    "repo": "https://github.com/raycast/extensions",
    "commit": "aad25dd3",
    "read": "2026-10-16",
    "files": [
        "extensions/anki/src/api/ankiClient.ts",
        "extensions/anki/src/api/axios.ts",
        "extensions/anki/src/api/cardActions.ts",
        "extensions/anki/src/api/deckActions.ts",
        "extensions/anki/src/api/guiActions.ts",
        "extensions/anki/src/api/mediaActions.ts",
        "extensions/anki/src/api/miscellaneousActions.ts",
        "extensions/anki/src/api/modelActions.ts",
        "extensions/anki/src/api/noteActions.ts",
        "extensions/anki/src/api/statisticActions.ts",
        "extensions/anki/src/decks.tsx",
        "extensions/anki/src/helpers/cardPages.ts",
        "extensions/anki/src/actions/EditNoteAction.tsx",
        "extensions/anki/src/actions/StudyDeck.tsx",
        "extensions/anki/src/tools/create-note.ts",
        "extensions/anki/src/tools/note-utils.ts",
        "extensions/anki/src/tools/search-notes.ts",
        "extensions/anki/src/util.ts",
    ],
    "uses": "version 6; params always ({} when empty); no key; axios with a 2 s timeout",
    "notes": ("Read-only actions are retried up to 5 times on a reset connection; a write that times out "
              "(2 s) or is reset is shown as 'Could not confirm whether Anki completed it'. Studying a deck "
              "grades cards through answerCards; cards with type-in answers or image occlusion are left to "
              "Anki's reviewer. addNote's duplicate options come from the preferences (allowDuplicate, "
              "scope deck or collection); attached files are sent by path. Note edits send only the changed "
              "fields through updateNote. updateNoteFields is defined but never called. "
              "Not tested: guiBrowse, guiDeckReview, sync."),
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}

# src/util.ts transformSubmittedData: the media lists are always sent, empty when no file is attached.
NO_MEDIA = {"audio": [], "picture": [], "video": []}

BY_PATH = [{"fields": [str], "filename": str, "path": str}]

CARD_READS = tuple(f"result[*].{key}" for key in (
    "cardId", "note", "question", "answer", "queue", "due", "deckName", "modelName",
    "reps", "lapses", "type", "mod", "fields.*.value", "fields.*.order"))

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {"note": {**NOTE, **NO_MEDIA, "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
            {"note": {**NOTE, **NO_MEDIA, "options": {"allowDuplicate": True, "duplicateScope": "deck"}}},
            {"note": {**NOTE, **NO_MEDIA, "options": {"allowDuplicate": False, "duplicateScope": "collection"}}},
            {"note": {**NOTE, **NO_MEDIA, "options": {"allowDuplicate": True, "duplicateScope": "collection"}}},
            # The create-note tool: fields left out are sent empty, tags default to none.
            {"note": {**NOTE, **NO_MEDIA, "fields": {str: (str, "")}, "tags": [],
                      "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
            # Files attached in the form, by path.
            {"note": {**NOTE, **NO_MEDIA, "picture": BY_PATH,
                      "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
            {"note": {**NOTE, "audio": BY_PATH, "picture": BY_PATH, "video": BY_PATH,
                      "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
        ],
        ("result", "error"),
    ),
    "answerCards": ([{"answers": [{"cardId": int, "ease": int}]}], ("result[0]", "error")),
    "areDue": ([{"cards": [int]}], ("result", "error")),
    # A deck with no cards asks for none.
    "cardsInfo": ([{"cards": [int]}, {"cards": []}], (*CARD_READS, "error")),
    "cardsToNotes": ([{"cards": [int]}], ("result", "error")),
    "createDeck": ([{"deck": str}], ("result", "error")),
    "deckNames": ([{}], ("result", "error")),
    "deckNamesAndIds": ([{}], ("result", "error")),
    "deleteDecks": ([{"decks": [str], "cardsToo": True}], ("error",)),
    "deleteNotes": ([{"notes": [int]}], ("error",)),
    "findCards": ([{"query": str}], ("result", "error")),
    "findModelsByName": (
        [{"modelNames": [str]}],
        ("result[*].name", "result[*].type", "result[*].flds[*].name", "result[*].flds[*].ord",
         "result[*].flds[*].description", "result[*].tmpls[*].name", "result[*].tmpls[*].ord", "error"),
    ),
    # The search-notes tool searches all notes with "".
    "findNotes": ([{"query": str}, {"query": ""}], ("result", "error")),
    "getCollectionStatsHTML": ([{"wholeCollection": True}], ("result", "error")),
    "getDeckStats": (
        [{"decks": [str]}],
        ("result.*.deck_id", "result.*.name", "result.*.new_count", "result.*.learn_count",
         "result.*.review_count", "result.*.total_in_deck", "error"),
    ),
    # The media folder, to show a card's files: a path on this machine.
    "getMediaDirPath": ([{}], ("result~type", "error")),
    "getTags": ([{}], ("result", "error")),
    "modelNames": ([{}], ("result", "error")),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].modelName", "result[*].tags", "result[*].fields.*.value",
         "result[*].fields.*.order", "result[*].cards", "error"),
    ),
    # EditNoteAction and the update-note tool: the changed fields, the tags when they changed.
    "updateNote": (
        [
            {"note": {"id": int, "fields": {str: str}}},
            {"note": {"id": int, "fields": {str: ""}}},
            {"note": {"id": int, "fields": {str: str}, "tags": [str]}},
            {"note": {"id": int, "tags": [str]}},
            {"note": {"id": int, "tags": []}},
        ],
        ("error",),
    ),
}
