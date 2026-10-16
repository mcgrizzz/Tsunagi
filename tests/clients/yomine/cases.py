"""Yomine: a Japanese immersion miner; its AnkiConnect path (used when GET /v1/health isn't Tsunagi's)."""
from clients.support import B64, case

CLIENT = {
    "name": "Yomine",
    "repo": "https://github.com/mcgrizzz/Yomine",
    "commit": "7044efc",
    "read": "2026-10-15",
    "files": [
        "src/anki/ankiconnect.rs",
        "src/anki/client.rs",
        "src/anki/sync.rs",
        "src-tauri/src/commands/mining.rs",
        "src-tauri/src/commands/anki.rs",
        "src-tauri/src/batches.rs",
        "src-tauri/src/media.rs",
    ],
    "uses": "reqwest; version 6, params left out when None, key only when set; one new connection per request",
    "notes": "Reads result and error only, never the HTTP status. An error containing 'duplicate' is a "
             "duplicate; one containing deck, model, note type, api key or permission is a setup error.",
}

# addNote's audio/picture items: the Attachment struct (kind skipped), always both lists.
CLIP = {"filename": "yomine-0123456789abcdef.mp3", "data": B64, "fields": ["Back"]}
SHOT = {"filename": "yomine-fedcba9876543210.png", "data": B64, "fields": ["Back"]}


def mined(fields, *, audio=(), picture=(), deck="Default", model="Basic", tags=("yomine",)):
    return {"note": {"deckName": deck, "modelName": model, "fields": fields, "tags": list(tags),
                     "audio": list(audio), "picture": list(picture),
                     "options": {"allowDuplicate": False}}}


def learning(col, c):
    """The seeded card in learning after one review: its revlog interval is negative seconds."""
    card = col.get_card(c["cid"])
    card.type = card.queue = 1
    card.due, card.reps = 1792000600, 1
    col.update_card(card)
    col.db.execute("insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
                   "values (?,?,?,?,?,?,?,?,?)", 1792000000000, c["cid"], -1, 3, -600, 0, 0, 5000, 0)


def review(col, c):
    card = col.get_card(c["cid"])
    card.type = card.queue = 2
    card.ivl, card.due, card.factor, card.reps = 12, col.sched.today + 12, 2500, 3
    col.update_card(card)
    col.db.execute("insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
                   "values (?,?,?,?,?,?,?,?,?)", 1792000000000, c["cid"], -1, 3, 12, 4, 2500, 6000, 1)


NOTE_READS = ["result[*].noteId", "result[*].modelName", "result[*].fields.*.value",
              "result[*].cards", "error"]


# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}
USES = [
    "deleteNotes",
    "findNotes everything",
    "modelFieldNames",
    "modelNamesAndIds",
    "notesInfo",
    "retrieveMediaFile",
    "version",
]

CASES = [
    # Detection when /v1/health isn't Tsunagi's (client.rs detect), and every sync's profile.
    case("getActiveProfile", "getActiveProfile"),
    # Sync (sync.rs harvest): every note, the ones edited since the last harvest, their
    # notes in one request and the first card's latest interval.
    case("findNotes edited", "findNotes", {"query": "edited:2"}),
    case("notesInfo missing note", "notesInfo", {"notes": [12345]}, reads=NOTE_READS),
    case("getIntervals new card", "getIntervals", lambda c: {"cards": [c["cid"]]}),
    case("getIntervals learning card", "getIntervals", lambda c: {"cards": [c["cid"]]}, setup=learning),
    case("getIntervals review card", "getIntervals", lambda c: {"cards": [c["cid"]]}, setup=review),
    # Settings (commands/anki.rs): note types and fields, then a sample note of the type.
    case("findNotes sample of a note type", "findNotes", {"query": 'note:"Basic"'}),
    case("findNotes sample, quote escaped", "findNotes", {"query": 'note:"Model \\"A\\""'}),
    # Mining (commands/mining.rs): dictionary media first, then the note.
    case("storeMediaFile", "storeMediaFile", {"filename": "yomine-0123456789abcdef.mp3", "data": B64},
         effects=True),
    case("storeMediaFile name taken by other bytes", "storeMediaFile",
         {"filename": "seed-1.txt", "data": B64}, effects=True),
    case("addNote no media", "addNote", mined({"Front": "猫", "Back": "cat"},
                                               tags=("yomine", "yomine::no-media")), effects=True),
    case("addNote with audio and picture", "addNote",
         mined({"Front": "猫", "Back": "cat"}, audio=[CLIP], picture=[SHOT]), effects=True),
    case("addNote duplicate", "addNote", mined({"Front": "犬", "Back": "dog"})),
    case("addNote missing deck", "addNote", mined({"Front": "猫", "Back": "cat"}, deck="Mining")),
    case("addNote missing model", "addNote", mined({"Front": "猫", "Back": "cat"}, model="Yomine")),
    # Attaching later (media.rs attach_cut): notesInfo, storeMediaFile, then the fields.
    case("updateNoteFields", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Back": "dog[sound:yomine-0123456789abcdef.mp3]"}}},
         reads=["error"], effects=True),
    # Undo (batches.rs undo_batch): which notes still exist, in chunks of 500, then delete.
    case("findNotes existing", "findNotes", lambda c: {"query": f"nid:{c['nid']},12345"}),
    # A mined file shown in Yomine: base64, or false when missing.
    case("retrieveMediaFile missing", "retrieveMediaFile", {"filename": "yomine-gone.mp3"}),
]
