"""Memento: mpv-based video player for learning Japanese, mining to Anki through AnkiConnect.

Its issue #353 ("'ascii' codec can't encode characters" with AnkiConnect's
2026-10-11 rewrite) is the {audio} marker: addNote with an audio `url` whose
query has the word in Japanese, unencoded (JapanesePod101 by default), and a
Japanese filename. The cases serve that URL from a local server (setup), since
tests can't reach the internet; the server answers only when the query arrives
decoded to the same word.
"""

from clients.support import NOTE

CLIENT = {
    "name": "Memento",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Video player for learning Japanese; mines words",
    "repo": "https://github.com/ripose-jp/Memento",
    "commit": "e45a792",
    "read": "2026-10-15",
    "files": [
        "src/anki/ankiclient.cpp",
        "src/anki/ankiconnect.h",
        "src/anki/notebuilder.cpp",
        "src/anki/glossarybuilder.cpp",
        "src/anki/ankiconfigkeys.h",
        "src/setting/keys.h",
    ],
    "uses": "Qt QJsonDocument, version 6, params left out when empty; multi's actions carry no version",
    "notes": "Every answer must be an object with exactly two keys, result and error, or it is refused "
             "(ankiclient.cpp processReply L882-931); a non-null error is shown as its text. 5 s timeout. "
             "guiBrowse (openDuplicates) isn't covered.",
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {"note": {**NOTE, "options": {"duplicateScope": "deck"}}},
            {
                "note": {
                    **NOTE,
                    "audio": [{"fields": [str], "filename": str, "skipHash": str, "url": str}],
                    "options": {"duplicateScope": "deck"},
                },
            },
            {
                "note": {
                    **NOTE,
                    "audio": [{"data": str, "fields": [str], "filename": str}],
                    "options": {"duplicateScope": "deck"},
                    "picture": [{"data": str, "fields": [str], "filename": str}],
                    "video": [{"data": str, "fields": [str], "filename": str}],
                },
            },
        ],
        ("",),
    ),
    "canAddNotes": (
        [
            {"notes": [{**NOTE, "options": {"duplicateScope": "deck"}}]},
            {"notes": [{**NOTE, "options": {"allowDuplicate": False}}]},
            {"notes": [{**NOTE, "options": {"allowDuplicate": True}}]},
        ],
        ("",),
    ),
    "deckNames": ([{}], ("",)),
    "modelFieldNames": ([{"modelName": str}], ("",)),
    "modelNames": ([{}], ("",)),
    "multi": ([{"actions": [{"action": "storeMediaFile"}]}], ("",)),
    "storeMediaFile": ([{"data": str, "filename": str}], ()),
    "version": ([{}], ("",)),
}
