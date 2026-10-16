"""anki.koplugin: KOReader plugin that makes Anki notes from dictionary lookups on an e-reader.

Every call goes through ankiconnect.lua `AnkiConnect:POST`: LuaSocket
http.request, POST, Content-Type application/json, a 1 s timeout, Basic auth
when the URL carries user:pass@. Tables are encoded with rapidjson; version
6, no params when there are none, `key` set from the API key setting (absent
when it's unset). deleteNotes is written by hand instead (note ids lose
digits through rapidjson on the device) and always carries `key`: null when
no API key is set. A non-200 status or a string `error` is an error,
otherwise `result` is used.

Offline: when requestPermission fails (no WiFi, Anki not running) the built
note is appended to anki.koplugin_notes.json. sync_offline_notes (when
online again, or from the menu) asks requestPermission, then for each queued
note fetches Forvo audio and the picture, and sends the same addNote as when
online; the ones that fail stay queued.
"""

from clients.support import NOTE

CLIENT = {
    "name": "anki.koplugin",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "KOReader plugin; mines words while reading",
    "repo": "https://github.com/Ajatt-Tools/anki.koplugin",
    "commit": "55b07ed",
    "read": "2026-10-16",
    "files": [
        "ankiconnect.lua",
        "ankinote.lua",
        "anki_configuration.lua",
        "main.lua",
        "forvo.lua",
    ],
    "uses": "LuaSocket and rapidjson; version 6, no params when empty, key from settings or absent (null on deleteNotes)",
    "notes": ("Every request times out after 1 s, so an addNote that makes AnkiConnect fetch Forvo audio "
              "slowly is reported as failed (or queued again) though Anki may have added it. audio and picture "
              "are single objects, not lists. requestPermission is asked before every add and delete; "
              "'denied' blocks. The connection test sends deckNames with the key only when requireApikey. "
              "duplicateScope is the dupe_scope setting (default deck), allowDuplicate allow_dupes "
              "(default false). Not tested: the offline queue's file handling (its requests are the "
              "ones below)."),
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    # AnkiNote:build: tags KOReader plus custom ones; audio (Forvo by URL) and picture (Mokuro CBZ
    # pages) added by handle_callbacks when their field is set and the fetch found something.
    "addNote": (
        [
            {"note": {**NOTE, "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
            {"note": {**NOTE, "options": {"allowDuplicate": True, "duplicateScope": "deck"}}},
            {
                "note": {
                    **NOTE,
                    "audio": {"fields": [str], "filename": str, "url": str},
                    "options": {"allowDuplicate": False, "duplicateScope": "deck"},
                },
            },
            {
                "note": {
                    **NOTE,
                    "audio": {"fields": [str], "filename": str, "url": str},
                    "options": {"allowDuplicate": False, "duplicateScope": "deck"},
                    "picture": {"data": str, "fields": [str], "filename": str},
                },
            },
        ],
        ("result", "error"),
    ),
    "deckNames": ([{}], ("error",)),
    "deleteNotes": ([{"notes": [int]}], ("error",)),
    "requestPermission": ([{}], ("result.permission", "result.requireApikey", "error")),
}
