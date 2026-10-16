"""Yomitan: pop-up dictionary browser extension; mines lookups into Anki notes.

Every call goes through ext/js/comm/anki-connect.js `_invoke`: POST
{action, params, version: 2}, params always present ({} when empty), `key`
only when one is set. Version 2 means bare results: an answer that is an
object with an `error` property (even null) is taken as an error, so each
case reads the whole answer unless only some fields of rows are read.
"""
import hashlib

from clients.support import B64, PNG, case

CLIENT = {
    "name": "Yomitan",
    "repo": "https://github.com/yomidevs/yomitan",
    "commit": "e7334a9",
    "read": "2026-10-15",
    "files": [
        "ext/js/comm/anki-connect.js",
        "ext/js/background/backend.js",
        "ext/js/data/anki-note-builder.js",
        "ext/js/data/anki-util.js",
        "ext/js/display/display-anki.js",
        "ext/js/pages/settings/anki-controller.js",
        "ext/js/pages/settings/anki-deck-generator-controller.js",
    ],
    "uses": "fetch, mode cors, credentials omit, Content-Type application/json; `multi` sub-actions carry no version",
    "notes": "Non-2xx is 'Anki connection error'; duplicates found by the substring "
             "'cannot create note because it is a duplicate'; falls back to canAddNotes on "
             "'Anki error: unsupported action'. Not tested: guiEditNote, guiBrowse, sync.",
}

V = 2
SHA1 = hashlib.sha1(PNG).hexdigest()
# anki-note-builder.js L117-132; tags default ["yomitan"], scope "collection".
COLLECTION = {"deckName": None, "checkChildren": False, "checkAllModels": False}


def ynote(front="犬", back="dog", deck="Default", model="Basic", scope="collection",
          scope_options=COLLECTION, allow=True, fields=None):
    return {
        "fields": fields if fields is not None else {"Front": front, "Back": back},
        "tags": ["yomitan"],
        "deckName": deck,
        "modelName": model,
        "options": {"allowDuplicate": allow, "duplicateScope": scope,
                    "duplicateScopeOptions": dict(scope_options)},
    }


def stripped(n):
    """backend.js partitionAddibleNotes: first field only, allowDuplicate false."""
    first = next(iter(n["fields"].items()))
    return {**n, "fields": dict([first]), "options": {**n["options"], "allowDuplicate": False}}


# deck-root becomes scope deck, the root deck's name, checkChildren true.
DECK_ROOT = {"deckName": "Default", "checkChildren": True, "checkAllModels": False}
ALL_MODELS = {"deckName": None, "checkChildren": False, "checkAllModels": True}

NOTES_INFO_READS = ["[*].noteId", "[*].modelName", "[*].fields.*.value", "[*].fields.*.order",
                    "[*].tags", "[*].cards", "error"]
CARDS_INFO_READS = ["[*].cardId", "[*].note", "[*].flags", "[*].queue", "error"]


# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 2, "params": "always", "key": "absent", "method": "POST"}
USES = [
    "cardsInfo new card",
    "deckNames",
    "findNotes empty query",
    "modelFieldNames",
    "modelFieldNames missing model",
    "modelNames",
    "notesInfo",
    "notesInfo -1",
    "suspend",
    "version",
]

CASES = [
    # _checkVersion before every call; isConnected on every lookup (uncached).
    # Settings page.
    # Every lookup: duplicate check of each entry x card format (backend.js L651-702).
    case("canAddNotesWithErrorDetail duplicate, new, empty", "canAddNotesWithErrorDetail",
         {"notes": [stripped(ynote()), stripped(ynote(front="猫", back="cat")),
                    stripped(ynote(front="", back="x"))]},
         version=V, reads=[""]),
    case("canAddNotesWithErrorDetail deck-root from a subdeck", "canAddNotesWithErrorDetail",
         {"notes": [stripped(ynote(deck="Default::Sub", scope="deck", scope_options=DECK_ROOT))]},
         version=V, reads=[""], setup=lambda col, c: col.decks.id("Default::Sub")),
    case("canAddNotesWithErrorDetail checkAllModels", "canAddNotesWithErrorDetail",
         {"notes": [stripped(ynote(model="Basic (and reversed card)", scope_options=ALL_MODELS))]},
         version=V, reads=[""]),
    # Fallback for an old AnkiConnect, and the deck generator: canAddNotes.
    case("canAddNotes duplicates allowed and not", "canAddNotes",
         {"notes": [ynote(), stripped(ynote())]}, version=V, reads=[""]),
    # Duplicates' ids: one query goes straight to multi (anki-connect.js L297-364).
    case("multi findNotes one query", "multi",
         {"actions": [{"action": "findNotes", "params": {"query": '"front:犬"'}}]},
         version=V, reads=[""]),
    # Several queries: the union first, then multi constrained to its ids.
    case("findNotes union", "findNotes",
         {"query": '("front:犬") or ("deck:Default" "front:猫")'}, version=V, reads=[""]),
    case("multi findNotes constrained to candidates", "multi", lambda c: {"actions": [
        {"action": "findNotes", "params": {"query": f'nid:{c["nid"]} ("front:犬")'}},
        {"action": "findNotes", "params": {"query": f'nid:{c["nid"]} ("deck:Default" "front:猫")'}},
    ]}, version=V, reads=[""]),
    # Duplicate details when tags/flags are shown or overwrite is on (backend.js L740-774).
    # {} (not null) for an unknown id: a null row throws in _normalizeNoteInfoArray.
    case("cardsInfo []", "cardsInfo", {"cards": []}, version=V, reads=[""]),
    # Settings "test note viewer" searches (anki-controller.js L556-566).
    case("findNotes test query reading", "findNotes", {"query": '"よむ" deck:current'},
         version=V, reads=[""]),
    case("findNotes test query deck:current", "findNotes", {"query": "deck:current"},
         version=V, reads=[""]),
    # Adding: media first (backend.js L2515-2640), the returned name is used.
    case("storeMediaFile dictionary media", "storeMediaFile",
         {"filename": f"yomitan_dictionary_media_{SHA1}.png", "data": B64},
         version=V, reads=[""], effects=True),
    case("storeMediaFile screenshot", "storeMediaFile",
         {"filename": "yomitan_browser_screenshot_2026-09-15-08-30-00-000.png", "data": B64},
         version=V, reads=[""], effects=True),
    case("addNote duplicate allowed", "addNote", {"note": ynote()}, version=V, reads=[""],
         effects=True),
    case("addNote deck-root", "addNote",
         {"note": ynote(front="猫", back="cat", deck="Default::Sub", scope="deck",
                        scope_options=DECK_ROOT)},
         version=V, reads=[""], effects=True, setup=lambda col, c: col.decks.id("Default::Sub")),
    case("addNote missing deck", "addNote", {"note": ynote(deck="Japanese")}, version=V,
         reads=[""]),
    # Overwrite: the whole new note plus id (display-anki.js L866-892).
    case("updateNoteFields whole note plus id", "updateNoteFields",
         lambda c: {"note": {**ynote(front="犬", back="dog; hound"), "id": c["nid"]}},
         version=V, reads=[""], effects=True),
    # Suspend new cards (backend.js L807-815): result must be true.
    case("findCards nid", "findCards", lambda c: {"query": f"nid:{c['nid']}"}, version=V,
         reads=[""]),
    # Deck generator (anki-deck-generator-controller.js L362-372).
    case("addNotes", "addNotes",
         {"notes": [ynote(front="猫", back="cat"), ynote(front="鳥", back="bird")]},
         version=V, reads=[""], effects=True),
    case("addNotes one empty", "addNotes",
         {"notes": [ynote(front="猫", back="cat"), ynote(front="", back="x")]},
         version=V, reads=[""], effects=True),
]
