"""LUTE (Learning Using Texts): a self-hosted reading app; exports terms as Anki notes.

Every AnkiConnect request is sent from the browser by lute/static/js/lute-anki.js
(jQuery $.ajax POST to the ankiconnect_url setting, default
http://127.0.0.1:8765); the Python server only builds the export posts
(lute/ankiexport/service.py _build_ankiconnect_post_json) and hands them to the
page. get_anki_specs sends two multis with version 6 and unversioned inner
actions; each export post is a multi without a version (storeMediaFile by URL
for each term image, then addNote), so its answer is the bare list. That post
is in its own catalog entries (catalog/lute.py); ENVELOPE is the specs' one.
"""

from clients.support import NOTE

CLIENT = {
    "name": "LUTE",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Learning-through-reading app; exports terms as notes",
    "repo": "https://github.com/LuteOrg/lute-v3",
    "commit": "933d084",
    "read": "2026-10-16",
    "files": [
        "lute/static/js/lute-anki.js",
        "lute/ankiexport/service.py",
        "lute/ankiexport/field_mapping.py",
    ],
    "uses": ("jQuery $.ajax from the Lute page, Content-Type application/json; get_anki_specs: multi version 6, "
             "inner actions unversioned; export posts: multi with no version at all"),
    "notes": ("A web page calling AnkiConnect: its origin (the Lute URL) must be in the allowed website origins. "
              "Any failure of get_anki_specs is shown as 'Unable to connect to AnkiConnect'. "
              "Images go by URL (storeMediaFile url = the Lute server's /userimages/...), so Anki must reach "
              "the Lute server. The export reads each inner answer of the bare multi list: an object with "
              "an error key is that export's error (a duplicate), anything else 'success'; the outer answer's "
              "own error isn't checked. Notes carry no options (AnkiConnect's duplicate check); fields "
              "that come out empty are left out."),
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    # Only inside multi (their answers are read through multi's).
    "addNote": ([{"note": NOTE}], ()),
    "deckNames": ([{}], ()),
    "modelFieldNames": ([{"modelName": str}], ()),
    "modelNames": ([{}], ()),
    "multi": (
        [
            # get_anki_specs (version 6): names, then each note type's fields.
            {"actions": [{"action": "deckNames"}, {"action": "modelNames"}]},
            {"actions": [{"action": "modelFieldNames"}]},
            # An export post (no version): term images, then the note; or the note alone.
            {"actions": [{"action": "storeMediaFile"}, {"action": "addNote"}]},
            {"actions": [{"action": "addNote"}]},
        ],
        ("",),
    ),
    "storeMediaFile": ([{"filename": str, "url": str}], ()),
}
