"""LinguaCafe: a self-hosted (Docker) reading app; adds highlighted words to Anki.

The PHP server talks to AnkiConnect, not the browser: app/Services/AnkiApiService.php
POSTs (Laravel Http::withBody, application/json) to the ankiConnectHost setting,
default http://host.docker.internal:8765 (database/seeders/SettingsSeeder.php).
Every body is a JSON string built by concatenation, version 6, params always
present, no key. addWord: addNote; on an error containing "was not found:
LinguaCafe", createModel and createDeck, then addNote again; on the duplicate
error (and the update setting on), findNotes then updateNoteFields.
"""

CLIENT = {
    "name": "LinguaCafe",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Self-hosted reading app; adds words to Anki",
    "repo": "https://github.com/simjanos-dev/LinguaCafe",
    "commit": "c1ea298",
    "read": "2026-10-16",
    "files": [
        "app/Services/AnkiApiService.php",
        "app/Http/Controllers/AnkiController.php",
        "database/seeders/SettingsSeeder.php",
    ],
    "uses": "Laravel Http client from the server, version 6, params always, no key",
    "notes": ("Runs in Docker and calls host.docker.internal: the request comes from the Docker network, "
              "addressed to that name, with no key (manual/Setup.md has AnkiConnect bound to 0.0.0.0). "
              "Errors are matched by text: 'was not found: LinguaCafe' (substring), exactly "
              "'cannot create note because it is a duplicate' and 'Model name already exists'. "
              "Word, reading, translation and sentence are pasted into the JSON unescaped, so a '\"', "
              "'\\' or a line break in them makes the body invalid JSON. The duplicate's lookup is "
              "deck:LinguaCafe::<Language> word:<word>, unquoted, so a word with a space finds nothing."),
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
OPTIONS = {
    "allowDuplicate": False,
    "duplicateScope": "deck",
    "duplicateScopeOptions": {"checkAllModels": False, "checkChildren": False, "deckName": str},
}

SENDS = {
    # Reading, translation and sentence are "" when not given.
    "addNote": (
        [
            {"note": {"deckName": str, "fields": {str: str}, "modelName": str, "options": OPTIONS}},
            {"note": {"deckName": str, "fields": {str: (str, "")}, "modelName": str, "options": OPTIONS}},
        ],
        ("error",),
    ),
    "createDeck": ([{"deck": str}], ("error",)),
    "createModel": (
        [{"cardTemplates": [{"Back": str, "Front": str, "Name": str}], "css": str,
          "inOrderFields": [str], "modelName": str}],
        ("error",),
    ),
    "findNotes": ([{"query": str}], ("result", "error")),
    "updateNoteFields": (
        [{"note": {"fields": {str: str}, "id": int}}, {"note": {"fields": {str: (str, "")}, "id": int}}],
        ("error",),
    ),
}
