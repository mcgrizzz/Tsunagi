"""Catalog entries first sent by anki-mcp-server (https://github.com/ankimcp/anki-mcp-server at e0e347f):
its requests that no other entry covers (tests/clients/anki_mcp_server/client.py)."""


from clients.support import B64, case, named


def revlog(col, cid, ivl, last, factor, ease=3, kind=1):
    col.db.execute("insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
                   "values (?,?,?,?,?,?,?,?,?)", 1792000000000, cid, -1, ease, ivl, last, factor, 6000, kind)

def review(col, c):
    """The seeded card as a review card due today, after one review."""
    card = col.get_card(c["cid"])
    card.type = card.queue = 2
    card.ivl, card.due, card.factor, card.reps, card.lapses = 12, col.sched.today, 2500, 3, 1
    col.update_card(card)
    revlog(col, c["cid"], 12, 4, 2500)

def suspended(col, c):
    col.sched.suspend_cards([c["cid"]])

def two_decks(col, c):
    """deckScopeQuery escapes '_': "deck:JLPT\\_N5" must not match JLPT-N5's card."""
    col.decks.id("JLPT_N5")
    col.set_deck([c["cid"]], col.decks.id("JLPT-N5"))

def subdeck(col, c):
    col.set_deck([c["cid"]], col.decks.id("Japanese::Vocab"))

BASIC_TEMPLATES = [{"Name": "Card 1", "Front": "{{Word}}", "Back": "{{FrontSide}}<hr id=answer>{{Meaning}}"}]

def add(fields, **options):
    """add_note / add_notes: tags and options only when given."""
    note = {"deckName": "Default", "modelName": "Basic", "fields": fields}
    tags = options.pop("tags", None)
    if tags:
        note["tags"] = tags
    if options:
        note["options"] = options
    return {"note": note}


ENTRIES = named("anki-mcp-server", [
    case("areSuspended suspended", "areSuspended", lambda c: {"cards": [c["cid"]]}, setup=suspended),
    case("answerCards bogus id", "answerCards", {"answers": [{"cardId": 12345, "ease": 3}]}),
    case("findCards escaped deck name", "findCards", {"query": '"deck:JLPT\\_N5" -is:suspended is:due'},
         setup=two_decks),
    # deck_stats on a parent: the subtree's names; keyed by new deck ids, so read whole.
    case("getDeckStats subtree", "getDeckStats", {"decks": ["Japanese", "Japanese::Vocab"]},
         setup=subdeck),
    case("getReviewsOfCards no reviews", "getReviewsOfCards", lambda c: {"cards": [c["cid"]]}),
    case("cardReviews", "cardReviews", {"startID": 1700000000000, "deck": "Default"}, setup=review),
    case("addNote no tags or options", "addNote", add({"Front": "猫", "Back": "cat"}), effects=True),
    case("addNote tags and duplicate scope", "addNote",
         add({"Front": "猫", "Back": "cat"}, tags=["ai", "n5"], allowDuplicate=False,
             duplicateScope="deck", duplicateScopeOptions={"deckName": "Default", "checkChildren": False,
                                                           "checkAllModels": False}), effects=True),
    case("addNote duplicate in deck scope", "addNote",
         add({"Front": "犬", "Back": "dog"}, allowDuplicate=False, duplicateScope="deck")),
    case("addNote duplicate allowed", "addNote", add({"Front": "犬", "Back": "dog"}, allowDuplicate=True),
         effects=True),
    case("findNotes bad query", "findNotes", {"query": "deck:Default ("}),
    # Models.
    case("createModel", "createModel", {"modelName": "Vocab", "inOrderFields": ["Word", "Meaning"],
                                         "cardTemplates": BASIC_TEMPLATES, "isCloze": False},
         reads=["result.id", "result.name", "error"]),
    case("updateModelStyling", "updateModelStyling", {"model": {"name": "Basic", "css": ".card { color: red; }"}},
         reads=["error"]),
    case("modelTemplates", "modelTemplates", {"modelName": "Basic"}),
    case("updateModelTemplates", "updateModelTemplates", {"model": {"name": "Basic", "templates": {
        "Card 1": {"Front": "{{Front}}!", "Back": "{{FrontSide}}<hr id=answer>{{Back}}"}}}}, reads=["error"]),
    case("modelFieldAdd", "modelFieldAdd", {"modelName": "Basic", "fieldName": "Notes"},
         reads=["error"], effects=True),
    case("modelFieldAdd at index", "modelFieldAdd", {"modelName": "Basic", "fieldName": "Notes", "index": 0},
         reads=["error"], effects=True),
    case("modelFieldRemove", "modelFieldRemove", {"modelName": "Basic", "fieldName": "Back"},
         reads=["error"], effects=True),
    case("modelFieldRename", "modelFieldRename",
         {"modelName": "Basic", "oldFieldName": "Back", "newFieldName": "Meaning"}, reads=["error"]),
    case("modelFieldReposition", "modelFieldReposition", {"modelName": "Basic", "fieldName": "Back", "index": 0},
         reads=["error"], effects=True),
    case("replaceTags", "replaceTags",
         lambda c: {"notes": [c["nid"]], "tag_to_replace": "seeded", "replace_with_tag": "ai"},
         reads=["error"], effects=True),
    case("clearUnusedTags", "clearUnusedTags", reads=["error"]),
    # Media: storeMediaFile always sends deleteExisting.
    case("storeMediaFile data", "storeMediaFile", {"filename": "ai.png", "deleteExisting": True, "data": B64},
         effects=True),
    case("storeMediaFile path", "storeMediaFile",
         lambda c: {"filename": "ai.png", "deleteExisting": True, "path": c["png_path"]}, effects=True),
    case("getMediaFilesNames {}", "getMediaFilesNames", {}),
    case("forgetCards", "forgetCards", lambda c: {"cards": [c["cid"]]}, reads=["error"], setup=review),
    case("setDueDate", "setDueDate", lambda c: {"cards": [c["cid"]], "days": "3"}, reads=["error"]),
])
