"""GoldenDict-ng: desktop dictionary (Qt); sends the article or selection to Anki as a note.

Every call goes through src/ankiconnector.cc `postToAnki`: a QNetworkAccessManager
POST, Content-Type application/json, 3 s transfer timeout. The bodies are
raw-string templates filled with QString::arg: version 6, params always, no
key. addNote's note always carries `"options": {"allowDuplicate": true}`,
`"tags": []` and an audio list: empty, or one item, base64 data the dictionary
gave or a web audio url (ui/articleview.cc sendToAnki L464-506), named
`<word>_<ms since epoch>.<ext>` and put in the definition field.
"""

from clients.support import PATH

CLIENT = {
    "name": "GoldenDict-ng",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Desktop dictionary; sends articles to Anki as notes",
    "repo": "https://github.com/xiaoyifang/goldendict-ng",
    "commit": "5b1bade",
    "read": "2026-10-16",
    "files": [
        "src/ankiconnector.cc",
        "src/ankiconnector.hh",
        "src/ui/articleview.cc",
        "src/config.cc",
        "src/ui/preferences.cc",
    ],
    "uses": "Qt QNetworkAccessManager, version 6, params always, no key; bodies are string templates",
    "notes": "A reply counts as success only when it is an object with exactly two keys, result and "
             "error, and error is null; anything else, or a transport error, shows 'Anki: post to Anki "
             "failed' (finishedSlot L123-147). The result (the note id) is never read. Fields are "
             "word, text and sentence, named in Preferences (defaults word, selected_text, "
             "marked_sentence, which Basic doesn't have); deck and model have no default. "
             "The sentence is the search line with the word in <b>. The audio filename keeps any "
             "'/' in the word. Not tested: guiBrowse (the ankisearch: link; its query is pasted "
             "into the template unescaped).",
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}

_NOTE = {"deckName": str, "modelName": str, "options": {"allowDuplicate": True}, "tags": []}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        [
            {"note": {**_NOTE, "fields": {str: str}, "audio": []}},
            # Nothing selected and no article id, or an empty search line: an empty field.
            {"note": {**_NOTE, "fields": {str: (str, "")}, "audio": []}},
            # Audio the dictionary served (buildAnkiAudioDataObject L84-111).
            {"note": {**_NOTE, "fields": {str: str},
                      "audio": [{"data": str, "fields": [str], "filename": str}]}},
            # A word with a slash in it ("AC/DC").
            {"note": {**_NOTE, "fields": {str: str},
                      "audio": [{"data": str, "fields": [str], "filename": PATH}]}},
            # A web audio link (sendToAnki L495-503).
            {"note": {**_NOTE, "fields": {str: str},
                      "audio": [{"fields": [str], "filename": str, "url": str}]}},
        ],
        ("~keys", "error"),
    ),
}
