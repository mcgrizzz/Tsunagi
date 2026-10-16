"""Manatan: immersion app for anime, manga and novels; mines dictionary lookups into Anki.

The desktop and web UI calls AnkiConnect through WebUI/src/Manatan/utils/anki.ts
`ankiConnect`: a browser fetch POST {action, params, version: 6} (params {}
when empty, no key, no Content-Type) to the configured URL
(http://127.0.0.1:8765 by default), a 20 s timeout. A truthy `error` throws;
otherwise `result` is returned. Any failure sends requestPermission (no
params) and, when it answers granted, the same request once more. The Android
build talks to AnkiDroid's API instead (bin/manatan_android/.../AnkiBridge.java),
not covered here.
"""

from clients.support import NOTE

CLIENT = {
    "name": "Manatan",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Immersion app for anime, manga and novels; mines words",
    "repo": "https://github.com/KolbyML/Manatan",
    "commit": "92d3787",
    "read": "2026-10-16",
    "files": [
        "WebUI/src/Manatan/utils/anki.ts",
        "WebUI/src/Manatan/utils/wordAudio.ts",
        "WebUI/src/Manatan/components/DictionaryView.tsx",
        "WebUI/src/Manatan/components/SettingsModal.tsx",
        "WebUI/src/Manatan/components/TextBox.tsx",
        "WebUI/src/features/anime/reader/components/AnimeVideoPlayer.tsx",
    ],
    "uses": "version 6; params always ({} when empty), except the requestPermission retry; no key; fetch without a Content-Type",
    "notes": ("Duplicates are looked up with findNotes (deck:\"…\", note:\"…\" and the target field), not canAddNotes; "
              "addNote then sends the duplicate scope setting as it is, so 'deck-root' reaches AnkiConnect, which "
              "checks the whole collection for any scope but 'deck'. 'Update last card' takes the newest note of "
              "findNotes added:1 if under 5 minutes old and sends its picture and audio as one object, not a list. "
              "Every failed request, a duplicate or a timeout included, is sent again after a granted "
              "requestPermission. Not tested: guiBrowse."),
}

# fetch with a string body and no Content-Type: text/plain;charset=UTF-8.
ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST", "content_type": "text"}

BY_DATA = {"data": str, "fields": [str], "filename": str}

BY_URL = {"fields": [str], "filename": str, "url": str}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            # anki.ts addNote: options always, allowDuplicate only for the 'add' duplicate action.
            {"note": {**NOTE, "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
            {"note": {**NOTE, "options": {"allowDuplicate": True, "duplicateScope": "deck"}}},
            {"note": {**NOTE, "options": {"allowDuplicate": False, "duplicateScope": "collection"}}},
            {"note": {**NOTE, "options": {"allowDuplicate": True, "duplicateScope": "collection"}}},
            {"note": {**NOTE, "options": {"allowDuplicate": False, "duplicateScope": "deck-root"}}},
            {"note": {**NOTE, "options": {"allowDuplicate": True, "duplicateScope": "deck-root"}}},
            # The page image (DictionaryView), with the word audio by URL into a field left empty.
            {"note": {**NOTE, "picture": [BY_DATA], "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
            {"note": {**NOTE, "fields": {str: (str, "")}, "picture": [BY_DATA], "audio": [BY_URL],
                      "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
            # AnimeVideoPlayer: the frame, the word audio and the sentence audio clip.
            {"note": {**NOTE, "fields": {str: (str, "")}, "picture": [BY_DATA],
                      "audio": [BY_URL, BY_DATA],
                      "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
        ],
        ("result", "error"),
    ),
    "deckNames": ([{}], ("result", "error")),
    "findNotes": ([{"query": str}], ("result", "error")),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelNames": ([{}], ("result", "error")),
    "notesInfo": ([{"notes": [int]}], ("result[*].fields.*.value", "error")),
    "requestPermission": ([{}], ("result.permission", "error")),
    "updateNoteFields": (
        [
            # updateLastCard: the sentence; the picture and audio fields emptied, the media as one object.
            {"note": {"id": int, "fields": {str: str}}},
            {"note": {"id": int, "fields": {str: (str, "")}, "picture": BY_DATA}},
            {"note": {"id": int, "fields": {str: ""}, "picture": BY_DATA, "audio": BY_DATA}},
            # DictionaryView's overwrite: the fields merged by update mode, the word audio in a list.
            {"note": {"id": int, "fields": {str: (str, "")}}},
            {"note": {"id": int, "fields": {str: (str, "")}, "picture": BY_DATA, "audio": [BY_URL]}},
        ],
        ("error",),
    ),
    "version": ([{}], ("result", "error")),
}
