"""Online Dictionary Helper (ODH): pop-up dictionary browser extension; adds looked-up words as notes.

Every call goes through src/bg/js/ankiconnect.js `ankiInvoke`, run in the
service worker: fetch POST {action, version: 6, params} to the configured URL,
params always ({} when empty), no key, a 3 s abort. The settings page and the
toolbar popup ask through the worker (options_api.js); the page's add button
sends a note definition that serviceworker.js formatNote (L113-150) turns into
addNote's note.
"""

from clients.support import NOTE

CLIENT = {
    "name": "Online Dictionary Helper",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Pop-up dictionary extension; adds words as notes",
    "repo": "https://github.com/ninja33/ODH",
    "commit": "d9b7bf8",
    "read": "2026-10-16",
    "files": [
        "src/bg/js/ankiconnect.js",
        "src/bg/js/serviceworker.js",
        "src/bg/js/options.js",
        "src/bg/js/popup.js",
        "src/bg/js/utils.js",
        "src/fg/js/frontend.js",
    ],
    "uses": "fetch, Content-Type application/json; charset=utf-8, version 6, params always, no key",
    "notes": "An answer must have exactly two own properties, result and error, or the call fails; "
             "a truthy error fails it, and every failure (timeout included) settles as null, shown "
             "as 'not connected' or a failed add. version is the connection check, asked live by the "
             "settings page, the popup and before drawing the add button. Notes go out with "
             "allowDuplicate from the duplicate setting (default allowed), the tags setting split on "
             "single spaces (default ODH), and the mapped fields, any of them empty when the "
             "dictionary gave nothing. With an audio field, that field is emptied and one audio "
             "object (not a list) with the dictionary's url is added to it.",
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}

READS = ("~keys", "result", "error")

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            # The defaults: duplicates allowed, tag ODH, every mapped field filled.
            {"note": {**NOTE, "options": {"allowDuplicate": True}}},
            {"note": {**NOTE, "options": {"allowDuplicate": False}}},
            # An empty tags setting, and fields the dictionary left empty.
            {"note": {**NOTE, "fields": {str: (str, "")}, "options": {"allowDuplicate": True}, "tags": []}},
            # An audio field: emptied, and the audio named ODH_<dict>_<encoded word>_<n>.mp3.
            {
                "note": {
                    **NOTE,
                    "audio": {"fields": [str], "filename": str, "url": str},
                    "fields": {str: (str, "")},
                    "options": {"allowDuplicate": True},
                },
            },
        ],
        READS,
    ),
    "deckNames": ([{}], READS),
    "modelFieldNames": ([{"modelName": str}], READS),
    "modelNames": ([{}], READS),
    "version": ([{}], READS),
}
