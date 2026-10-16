"""LunaTranslator: a visual-novel translator whose dictionary window adds the looked-up word to Anki."""

CLIENT = {
    "name": "LunaTranslator",
    "repo": "https://github.com/HIllya51/LunaTranslator",
    "commit": "0ee08c6",
    "read": "2026-10-15",
    "files": [
        "src/LunaTranslator/myutils/ankiconnect.py",
        "src/LunaTranslator/gui/showword.py",
        "src/LunaTranslator/defaultconfig/static_data.json",
    ],
    "uses": "requests.get with a JSON body, version 6, params always sent (ankiconnect.py invoke)",
    "notes": "Needs exactly the two keys result and error; matches 'Model name already exists' "
             "and 'cannot create note because it is a duplicate' exactly.",
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "GET"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {
                "note": {
                    "audio": [],
                    "deckName": str,
                    "fields": {str: (str, "")},
                    "modelName": str,
                    "options": {"allowDuplicate": True},
                    "picture": [],
                    "tags": [],
                    "video": [],
                },
            },
            {
                "note": {
                    "audio": [],
                    "deckName": str,
                    "fields": {str: (str, "")},
                    "modelName": str,
                    "options": {"allowDuplicate": True},
                    "picture": [{"fields": [str], "filename": str, "path": str}],
                    "tags": [],
                    "video": [],
                },
            },
            {
                "note": {
                    "audio": [],
                    "deckName": str,
                    "fields": {str: (str, "")},
                    "modelName": str,
                    "options": {"allowDuplicate": False},
                    "picture": [],
                    "tags": [],
                    "video": [],
                },
            },
        ],
        ("",),
    ),
    "createDeck": ([{"deck": str}], ("",)),
    "createModel": (
        [
            {
                "cardTemplates": [{"Back": str, "Front": str, "Name": str}],
                "css": str,
                "inOrderFields": [str],
                "isCloze": False,
                "modelName": str,
            },
        ],
        ("",),
    ),
    "deleteNotes": ([{"notes": [int]}], ("",)),
    "updateModelStyling": ([{"model": {"css": str, "name": str}}], ("",)),
    "updateModelTemplates": (
        [{"model": {"name": str, "templates": {str: {"Back": str, "Front": str}}}}],
        ("",),
    ),
}
