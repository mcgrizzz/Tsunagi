"""Catalog entries first sent by Raycast Anki (https://github.com/raycast/extensions at aad25dd3):
its requests that no other entry covers (tests/clients/raycast_anki/client.py)."""


from clients.support import PNG, case, named, note

EVERYTHING = ("",)

# src/util.ts transformSubmittedData: every media list sent, empty unless a file is attached.
NO_MEDIA = {"audio": [], "picture": [], "video": []}

def add(options, **over):
    """noteActions.addNote: the note and the preferences' duplicate options."""
    return {"note": note(**{**NO_MEDIA, "options": options, **over})}

def keep(dup, scope):
    return {"allowDuplicate": dup, "duplicateScope": scope}

NEW = {"Front": "猫", "Back": "cat"}

def other_deck(col, ctx):
    col.decks.id("Other")

def clips(col, ctx):
    """A sound and a video file next to the seeded picture, attached by path."""
    out = {}
    for name in ("clip.mp3", "clip.mp4"):
        path = ctx["png_path"].rsplit("/", 1)[0] + "/" + name
        with open(path, "wb") as f:
            f.write(PNG)
        out[name.replace(".", "_")] = path
    return out

def by_path(c, key, name):
    return [{"path": c[key], "filename": name, "fields": ["Back"]}]

def review_due(col, ctx):
    """The seeded card a review card due today, after one review; a second, new card (cid2)."""
    card = col.get_card(ctx["cid"])
    card.type = card.queue = 2
    card.ivl, card.due, card.factor, card.reps = 12, col.sched.today, 2500, 3
    col.update_card(card)
    col.db.execute("insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
                   "values (1700000000000, ?, -1, 3, 12, 4, 2500, 6000, 1)", ctx["cid"])
    n = col.new_note(col.models.by_name("Basic"))
    n["Front"], n["Back"] = "猫", "cat"
    col.add_note(n, 1)
    return {"cid2": col.card_ids_of_note(n.id)[0]}


ENTRIES = named("Raycast Anki", [
    # Add Note form and the create-note tool (noteActions.addNote), preferences' defaults first.
    case("addNote", "addNote", add(keep(False, "deck"), fields=NEW), reads=EVERYTHING, effects=True),
    case("addNote duplicate, deck scope", "addNote", add(keep(False, "deck")), reads=EVERYTHING),
    case("addNote duplicate allowed, deck scope", "addNote", add(keep(True, "deck")),
         reads=EVERYTHING, effects=True),
    case("addNote duplicate in another deck, collection scope", "addNote",
         add(keep(False, "collection"), deckName="Other"), reads=EVERYTHING, setup=other_deck),
    case("addNote duplicate allowed, collection scope", "addNote", add(keep(True, "collection")),
         reads=EVERYTHING, effects=True),
    case("addNote empty field, no tags", "addNote",
         add(keep(False, "deck"), fields={"Front": "猫", "Back": ""}, tags=[]), reads=EVERYTHING, effects=True),
    case("addNote picture by path", "addNote",
         lambda c: add(keep(False, "deck"), fields=NEW, picture=by_path(c, "png_path", "local.png")),
         reads=EVERYTHING, effects=True),
    case("addNote audio, picture and video by path", "addNote",
         lambda c: add(keep(False, "deck"), fields=NEW, audio=by_path(c, "clip_mp3", "clip.mp3"),
                       picture=by_path(c, "png_path", "local.png"), video=by_path(c, "clip_mp4", "clip.mp4")),
         reads=EVERYTHING, effects=True, setup=clips),
    # Study Deck (cardActions.cardsDueInfo, answerCard).
    case("areDue review card and new card", "areDue", lambda c: {"cards": [c["cid"], c["cid2"]]},
         reads=EVERYTHING, setup=review_due),
    case("answerCards new card, good", "answerCards", lambda c: {"answers": [{"cardId": c["cid"], "ease": 3}]},
         reads=EVERYTHING, effects=True),
    # Browse Cards: Delete Note (noteActions.deleteNote).
    case("cardsToNotes", "cardsToNotes", lambda c: {"cards": [c["cid"]]}, reads=EVERYTHING),
    # View Stats. The report ends "Generated on <the time>": only its type is compared.
    case("getCollectionStatsHTML", "getCollectionStatsHTML", {"wholeCollection": True},
         reads=("result~type", "error")),
    # Edit Note and the update-note tool (noteActions.updateNote): changed fields, tags when changed.
    case("updateNote field", "updateNote", lambda c: {"note": {"id": c["nid"], "fields": {"Back": "dog!"}}},
         reads=EVERYTHING, effects=True),
    case("updateNote field cleared", "updateNote", lambda c: {"note": {"id": c["nid"], "fields": {"Back": ""}}},
         reads=EVERYTHING, effects=True),
    case("updateNote field and tags", "updateNote", lambda c: {"note": {
        "id": c["nid"], "fields": {"Back": "dog!"}, "tags": ["seeded", "edited"]}}, reads=EVERYTHING, effects=True),
    case("updateNote tags", "updateNote", lambda c: {"note": {"id": c["nid"], "tags": ["edited"]}},
         reads=EVERYTHING, effects=True),
    case("updateNote no tags", "updateNote", lambda c: {"note": {"id": c["nid"], "tags": []}},
         reads=EVERYTHING, effects=True),
])
