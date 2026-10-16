"""mokuro-reader: manga reader (web app) making or updating Anki cards from a page crop."""
from clients.support import B64, case

CLIENT = {
    "name": "mokuro-reader",
    "repo": "https://github.com/Gnathonic/mokuro-reader",
    "commit": "bfaeb48",
    "read": "2026-10-15",
    "files": [
        "src/lib/anki-connect/index.ts",
        "src/lib/components/Reader/TextBoxPicker.svelte",
        "src/lib/components/Reader/Reader.svelte",
        "src/lib/components/Reader/AnkiFieldModal.svelte",
    ],
    "uses": "ankiConnect / ankiConnectRaw (index.ts L294-309, L540-585): {action, params, version: 6}, "
            "params always sent ({} when empty), no key, no multi; version and requestPermission without params",
    "notes": "HTTP status ignored. An answer with an error fails; otherwise result is returned, and "
             "updateNoteFields fails when result is undefined (index.ts L1054-1059), so result must be "
             "present even when null. createDeck null means AnkiConnect Android (index.ts L264-274). "
             "Update accepts only a note younger than 5 minutes by its id (index.ts L608-610, L940; TextBoxPicker.svelte L125).",
}

TEST_DECK = "__mokuro_test_1760000000000"
PICTURE = {"filename": "mokuro_One_Piece_v01_0001.jpg", "data": B64, "fields": ["Back"]}


# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}
USES = [
    "deckNames",
    "findNotes newest (added:1)",
    "modelFieldNames",
    "modelNames",
    "notesInfo",
    "requestPermission",
    "version",
]

CASES = [
    # Connection (index.ts L229-289, L459-538): version; requestPermission only after a CORS failure.
    case("modelFieldNames missing model", "modelFieldNames", {"modelName": "Japanese (mokuro)"}),
    # Android detection: a test deck made and deleted.
    case("createDeck test deck", "createDeck", {"deck": TEST_DECK}, effects=True),
    case("deleteDecks test deck", "deleteDecks", {"decks": [TEST_DECK], "cardsToo": True},
         setup=lambda col, c: col.decks.id(TEST_DECK), effects=True),
    # Create a card (index.ts L683-892): a missing deck is made, then addNote; picture-only fields
    # are left out of fields, and tags only when there are some.
    case("createDeck resolved deck", "createDeck", {"deck": "Mining::One_Piece"}, effects=True),
    case("addNote picture", "addNote", {"note": {
        "deckName": "Default", "modelName": "Basic", "fields": {"Front": "犬"},
        "options": {"allowDuplicate": True}, "picture": [PICTURE], "tags": ["mining", "One_Piece"]}},
        effects=True),
    case("addNote no tags", "addNote", {"note": {
        "deckName": "Default", "modelName": "Basic", "fields": {"Front": "猫", "Back": "cat"},
        "options": {"allowDuplicate": True}, "picture": [PICTURE]}}, effects=True),
    # Update the last card (index.ts L587-606, L898-1067; TextBoxPicker.svelte L113-155).
    case("updateNoteFields picture field cleared", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Front": "犬が走る", "Back": ""}, "picture": [PICTURE]}}, effects=True),
    case("updateNoteFields picture after existing", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Front": "犬", "Back": "dog"}, "picture": [PICTURE]}}, effects=True),
    case("updateNoteFields missing note", "updateNoteFields", {"note": {
        "id": 12345, "fields": {"Front": "犬", "Back": ""}, "picture": [PICTURE]}}),
    case("addTags", "addTags", lambda c: {"notes": [c["nid"]], "tags": "mining One_Piece"}, effects=True),
]
