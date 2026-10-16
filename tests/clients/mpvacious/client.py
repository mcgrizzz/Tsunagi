"""mpvacious: mpv script that makes Anki cards from the video being watched.

Every call goes through mpvacious/anki/ankiconnect.lua `execute`: the request
table is serialized by mpv's utils.format_json (an empty Lua table becomes
[], so changeDeck's cards and an empty tag list are []) and posted by curl as
a subprocess (platform/nix.lua: `curl -s URL -X POST -d JSON`, no
Content-Type, so application/x-www-form-urlencoded; platform/win.lua: the
JSON through a temp file, Content-Type application/json). Version 6, params
left out when there are none, `key` only when one is configured. Media isn't
sent: it asks getMediaDirPath and ffmpeg/mpv write the audio and snapshot
there, then the fields name them ([sound:...], <img src=...>).
"""

from clients.support import NOTE

CLIENT = {
    "name": "mpvacious",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "mpv script; makes cards from video",
    "repo": "https://github.com/Ajatt-Tools/mpvacious",
    "commit": "26e4102",
    "read": "2026-10-16",
    "files": [
        "mpvacious/anki/ankiconnect.lua",
        "mpvacious/anki/note_update_context.lua",
        "mpvacious/anki/new_note_checker.lua",
        "mpvacious/main.lua",
        "mpvacious/platform/nix.lua",
        "mpvacious/platform/win.lua",
        "mpvacious/config/defaults.lua",
    ],
    "uses": "curl subprocess, mpv format_json; version 6, params left out when empty, key only when configured",
    "notes": ("An answer is taken as an error when curl fails, the body isn't JSON or error isn't null; "
              "otherwise result is used. The default tag \"subs2srs %n\" is sent as one tag with a space "
              "in it. Media files are written straight into the folder getMediaDirPath names, so Anki must "
              "run on the same machine. create_deck (off by default) makes the deck with changeDeck of no "
              "cards. Updating notes: findNotes added:1 (or guiSelectedNotes), notesInfo, then "
              "updateNoteFields and addTags. Not tested: guiAddCards, guiBrowse, guiSelectedNotes."),
}

# curl -d on Linux and macOS: the form Content-Type (Windows sends application/json).
ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST", "content_type": "form"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    # make_add_note_request: allowDuplicate from allow_duplicates (default yes), scope always deck,
    # tags [note_tag] or [] when the tag is empty.
    "addNote": (
        [
            {"note": {**NOTE, "options": {"allowDuplicate": True, "duplicateScope": "deck"}}},
            {"note": {**NOTE, "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
            {"note": {**NOTE, "options": {"allowDuplicate": True, "duplicateScope": "deck"}, "tags": []}},
        ],
        ("result", "error"),
    ),
    "addTags": ([{"notes": [int], "tags": str}], ()),
    "changeDeck": ([{"cards": [], "deck": str}], ("error",)),
    "findModelsByName": ([{"modelNames": [str]}], ("result[0].flds[*].ord", "result[0].flds[*].name", "error")),
    # 'added:1 "note:M" "deck:D"' (new_note_checker.lua) and "added:1" (get_last_note_ids).
    "findNotes": ([{"query": str}], ("result", "error")),
    "getMediaDirPath": ([{}], ("result", "error")),
    "notesInfo": ([{"notes": [int]}], ("result[*].noteId", "result[*].fields.*.value", "error")),
    # Fields joined with what the note had: one with nothing either side is "".
    "updateNoteFields": ([{"note": {"fields": {str: (str, "")}, "id": int}}], ("result", "error")),
}
