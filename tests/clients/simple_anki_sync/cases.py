"""simple-anki-sync: Obsidian plugin syncing Markdown tables to Anki, one request at a time.

sendRequest (anki-service.ts) sends version 6 with params always present ({}
when empty) and rejects an answer without both result and error keys, or
with a non-null error. Since PR #4 (2026-10-12) it sends card ids, read from
notesInfo, to cardsInfo and changeDeck.
"""
from clients.support import B64, case

CLIENT = {
    "name": "simple-anki-sync",
    "repo": "https://github.com/russluber/simple-anki-sync",
    "commit": "36ddadd",
    "read": "2026-10-15",
    "files": [
        "src/anki-service.ts",
        "src/main.ts",
        "src/settings.ts",
        "src/deck-name.ts",
    ],
    "notes": ("Before PR #4 (7e84eed) it sent the note id as a card id to cardsInfo and "
              "changeDeck and read cardsInfo[0].deckName. No key."),
}

MANAGED = "obsidian_simple_anki_sync_created"
DECK = "Obsidian::My Deck"  # deck-name.ts: #anki/Obsidian/My--Deck
LINK = '<br><small><a href="obsidian://open?vault=v&file=a.md" style="text-decoration:none;color:grey;font-size:0.8em;">Obsidian Note</a></small>'


def make_deck(col, ctx):
    col.decks.id(DECK)


def add(fields, model="Basic"):
    """anki-service.ts addNote: no options, the managed tag last."""
    return {"note": {"deckName": DECK, "modelName": model, "fields": fields, "tags": [MANAGED]}}



# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}
USES = [
    "cardsInfo new card",
    "createDeck existing",
    "deckNames",
    "deleteNotes",
    "modelNames",
    "notesInfo",
    "requestPermission",
]

CASES = [
    # verifyConnection before every sync, vault sync and unsync: no error, then an array.
    # Settings tab: the note type list.
    # syncFile: the deck from the #anki/... tag, made every time ("deck already exists" tolerated).
    case("createDeck", "createDeck", {"deck": DECK}, reads=["error"], effects=True),
    # Media before each note (main.ts syncFile); the returned name is not used.
    case("storeMediaFile base64", "storeMediaFile", {"filename": "Pasted image 1.png", "data": B64},
         reads=["error"], effects=True),
    # New note: a number is the id; "cannot create note because it is empty" means a note type
    # without Front and Back.
    case("addNote", "addNote", add({"Front": "猫", "Back": "cat" + LINK}), setup=make_deck, effects=True),
    case("addNote type without Front/Back", "addNote", add({"Front": "猫", "Back": "cat"}, model="Cloze"),
         setup=make_deck),
    case("addNote empty front", "addNote", add({"Front": "", "Back": "cat"}), setup=make_deck),
    case("addNote duplicate", "addNote", add({"Front": "犬", "Back": "dog"}), setup=make_deck),
    # updateNote: fields, then notesInfo for the tags, then updateNoteTags if the managed tag is missing.
    case("updateNoteFields", "updateNoteFields",
         lambda c: {"note": {"id": c["nid"], "fields": {"Front": "犬", "Back": "dog" + LINK}}}, effects=True),
    case("updateNoteFields missing note", "updateNoteFields",
         {"note": {"id": 1234567890123, "fields": {"Front": "犬", "Back": "dog"}}}, reads=["error"]),
    # fetchNotesInfo: as many infos as ids, each with its noteId and number cards; tags for updateNote.
    case("updateNoteTags", "updateNoteTags", lambda c: {"note": c["nid"], "tags": ["seeded", MANAGED]},
         effects=True),
    # fetchCardInfo with the note's card ids: each with its cardId and a string deckName.
    # changeDeck of the cards not in the deck yet: success is null (or true).
    case("changeDeck", "changeDeck", lambda c: {"cards": [c["cid"]], "deck": DECK}, setup=make_deck),
    case("cardsInfo after changeDeck", "cardsInfo", lambda c: {"cards": [c["cid"]]},
         reads=["result[*].cardId", "result[*].deckName", "error"],
         setup=lambda col, c: col.set_deck([c["cid"]], col.decks.id(DECK))),
    # Rows removed from the file, and unSyncFile.
]
