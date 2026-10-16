"""Yanki: Markdown to Anki sync (CLI, and yanki-obsidian), through yanki-connect."""
from clients.support import B64, case, note

CLIENT = {
    "name": "Yanki",
    "repo": "https://github.com/kitschpatrol/yanki",
    "commit": "60603b4",
    "read": "2026-10-15",
    "files": [
        "src/lib/utilities/anki-connect.ts",
        "src/lib/model/model.ts",
    ],
    "uses": "yanki-connect 2a2bd21 (src/client.ts): version 6, params left out when empty, every call one at a time",
    "notes": "Matches error messages exactly; needs HTTP 200.",
}

BASIC = {
    "cardTemplates": [{"Back": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}", "Front": "{{Front}}",
                       "YankiNamespace": "{{YankiNamespace}}"}],
    "inOrderFields": ["Front", "Back", "YankiNamespace"],
    "modelName": "Yanki - Basic",
}


# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}
USES = [
    "deckNames",
    "deleteDecks [] cardsToo",
    "deleteMediaFile",
    "deleteNotes []",
    "getDeckConfig",
    "getDeckConfig missing deck",
    "getDeckStats",
    "modelStyling",
    "notesInfo with a missing id",
    "requestPermission",
]

CASES = [
    # Before every operation (anki-connect.ts requestAnkiPermission).
    # Every sync: its notes, their decks and whether each deck is filtered.
    case("findNotes namespace", "findNotes", {"query": '"YankiNamespace:Yanki CLI Default Namespace"'}),
    case("findNotes deck", "findNotes", {"query": '"deck:Default"'}),
    case("getDecks", "getDecks", lambda c: {"cards": [c["cid"]]}),
    # Sent even when empty.
    case("deleteDecks a deck", "deleteDecks", {"cardsToo": True, "decks": ["Yanki::Old"]},
         setup=lambda col, c: col.decks.id("Yanki::Old"), effects=True),
    case("deckNames after a deck is made", "deckNames", setup=lambda col, c: col.decks.id("Yanki::Sub")),
    # Notes: missing models and decks are found by their error text, then made.
    case("createModel", "createModel", BASIC, reads=["error"]),
    case("createModel existing name", "createModel", {**BASIC, "modelName": "Basic"}),
    case("addNote", "addNote", {"note": {**note(fields={"Front": "猫", "Back": "cat"}),
                                         "options": {"allowDuplicate": True}}}, effects=True),
    case("addNote missing model", "addNote", {"note": {**note(modelName="Yanki - Basic"),
                                                       "options": {"allowDuplicate": True}}}),
    case("addNote missing deck", "addNote", {"note": {**note(deckName="Yanki"),
                                                      "options": {"allowDuplicate": True}}}),
    case("createDeck", "createDeck", {"deck": "Yanki"}, reads=["error"]),
    case("changeDeck", "changeDeck", lambda c: {"cards": [c["cid"]], "deck": "Yanki::Sub"}),
    # updateNoteModel with the whole local note: id, plus noteId and deckName.
    case("updateNoteModel extra keys", "updateNoteModel", lambda c: {"note": {
        "id": c["nid"], "noteId": c["nid"], "deckName": "Default", "modelName": "Basic",
        "fields": {"Front": "猫", "Back": "cat"}, "tags": ["y"], "cards": [c["cid"]]}}, effects=True),
    case("updateNoteModel missing model", "updateNoteModel", lambda c: {"note": {
        "id": c["nid"], "modelName": "Yanki - Basic", "fields": {"Front": "猫", "Back": "cat"}, "tags": []}}),
    # Styling command.
    case("modelStyling missing model", "modelStyling", {"modelName": "Yanki - Basic"}),
    case("updateModelStyling", "updateModelStyling", {"model": {"name": "Basic", "css": ".card { color: red; }"}}),
    # Media: exists?, then store and compare the returned name.
    case("getMediaFilesNames namespace", "getMediaFilesNames", {"pattern": "yanki-media-*"}),
    case("getMediaFilesNames exact", "getMediaFilesNames", {"pattern": "seed-1.txt"}),
    case("storeMediaFile deleteExisting", "storeMediaFile",
         {"data": B64, "deleteExisting": True, "filename": "yanki-media-ns-1a2b.png"}, effects=True),
]
