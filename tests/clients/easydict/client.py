"""Easydict: a macOS dictionary and translator app whose result view adds the lookup to Anki.

Both calls go through AnkiConnectClient.swift performRequest: an Alamofire
POST of {action, version: 6, params} (JSONSerialization), never a key, to
the configured endpoint (http://127.0.0.1:8765 by default). parseResponse
needs an `error` key: a non-null error is shown as Anki wrote it, else a
non-null `result` of the right type (a positive integer note id for addNote,
a list of strings for modelFieldNames).
"""

CLIENT = {
    "name": "Easydict",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "macOS dictionary and translator; adds looked-up words",
    "repo": "https://github.com/tisfeng/Easydict",
    "commit": "af5b654",
    "read": "2026-10-16",
    "files": [
        "Easydict/Swift/Feature/AnkiConnect/AnkiConnectClient.swift",
        "Easydict/Swift/View/SettingView/Tabs/TabView/AdvancedTabAnkiSection.swift",
        "Easydict/Swift/Feature/Configuration/Defaults.Keys+Extension.swift",
        "Easydict/objc/ViewController/View/WordResultView/EZWordResultView.m",
    ],
    "uses": "Alamofire with validate() (non-2xx fails), timeout 8 s; params always sent",
    "notes": ("Off by default (enableAnkiConnect). Defaults: deck 'Default', note type 'Basic', "
              "Word into Front and the full result into Back, tag 'easydict', duplicates refused. "
              "Each Anki field is a template of Easydict variables; an empty variable leaves the field "
              "empty. The settings page asks modelFieldNames to fill the field mapping."),
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
                    "options": {"allowDuplicate": False},
                    "tags": [str],
                },
            },
            # A mapped variable this lookup has no value for (phonetic, etymology...).
            {
                "note": {
                    "deckName": str,
                    "fields": {str: (str, "")},
                    "modelName": str,
                    "options": {"allowDuplicate": False},
                    "tags": [str],
                },
            },
        ],
        ("result", "error"),
    ),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
}
