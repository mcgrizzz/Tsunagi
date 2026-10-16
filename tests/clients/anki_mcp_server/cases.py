"""anki-mcp-server: an MCP server giving AI assistants Anki tools, each one or more AnkiConnect actions."""
from clients.support import B64, case

CLIENT = {
    "name": "anki-mcp-server",
    "repo": "https://github.com/ankimcp/anki-mcp-server",
    "commit": "e0e347f",
    "read": "2026-10-15",
    "files": [
        "src/mcp/clients/anki-connect.client.ts",
        "src/mcp/utils/card-validation.utils.ts",
        "src/mcp/utils/card-suspension.utils.ts",
        "src/mcp/utils/card-states.utils.ts",
        "src/mcp/utils/anki.utils.ts",
        "src/mcp/primitives/essential/tools/",
        "src/mcp/primitives/gui/tools/",
    ],
    "uses": "ky; version 6 (ANKI_CONNECT_API_VERSION), params left out when the tool passes none "
            "(JSON.stringify drops undefined), one request at a time behind a global mutex",
    "notes": "A truthy error throws 'AnkiConnect error: <error>'; tools then match its text "
             "(duplicate, model, deck, field, not found, query, already exists). {} and null mark "
             "missing cards. HTTP 403 means a key problem; POST is retried on 408/413/429/5xx.",
}


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


CARD_READS = ["result[*].cardId", "result[*].question", "result[*].answer", "result[*].deckName",
              "result[*].modelName", "result[*].due", "result[*].interval", "result[*].factor",
              "result[*].reps", "result[*].lapses", "result[*].type", "result[*].note", "error"]
NOTE_READS = ["result[*].noteId", "result[*].modelName", "result[*].tags", "result[*].fields",
              "result[*].cards", "error"]
STATS_READS = ["result.*.deck_id", "result.*.total_in_deck", "result.*.new_count",
               "result.*.learn_count", "result.*.review_count", "error"]
# card-states.utils.ts CARD_STATE_QUERIES, one findCards each.
STATES = {
    "new": "is:new -is:suspended -is:buried",
    "learning": "is:learn -is:suspended -is:buried",
    "review": "is:review -is:learn -is:suspended -is:buried",
    "suspended": "is:suspended",
    "buried": "is:buried",
}
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



# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}
USES = [
    "cardsInfo new card",
    "cardsInfo with a missing id",
    "cardsModTime with a missing id",
    "deckNames",
    "deckNamesAndIds",
    "deleteMediaFile",
    "deleteNotes",
    "findNotes deck",
    "getDeckStats",
    "getTags",
    "modelFieldNames",
    "modelNames",
    "modelStyling",
    "notesInfo with a missing id",
    "removeTags",
    "retrieveMediaFile",
    "suspend",
]

CASES = [
    # Existence checks before a write (card-validation.utils.ts, card-suspension.utils.ts,
    # rate-card.tool.ts, change-deck): {} and null mark a missing card.
    case("areSuspended one missing", "areSuspended", lambda c: {"cards": [c["cid"], 12345]}),
    case("areSuspended suspended", "areSuspended", lambda c: {"cards": [c["cid"]]}, setup=suspended),
    case("answerCards bogus id", "answerCards", {"answers": [{"cardId": 12345, "ease": 3}]}),
    case("answerCards", "answerCards", lambda c: {"answers": [{"cardId": c["cid"], "ease": 3}]}),
    # Card reads: get_cards, get_due_cards, present_card, rate_card, forget_cards, set_due_date.
    case("cardsInfo review card", "cardsInfo", lambda c: {"cards": [c["cid"]]}, reads=CARD_READS,
         setup=review),
    case("findCards get_cards due", "findCards", {"query": "-is:suspended is:due"}, setup=review),
    case("findCards get_cards new in deck", "findCards", {"query": '"deck:Default" -is:suspended is:new'}),
    case("findCards get_due_cards", "findCards", {"query": "-is:suspended (is:due OR is:learn OR is:new)"}),
    case("findCards escaped deck name", "findCards", {"query": '"deck:JLPT\\_N5" -is:suspended is:due'},
         setup=two_decks),
    case("findCards suspended", "findCards", {"query": "is:suspended"}, setup=suspended),
    # collection_stats: decks, their stats, every card, five state counts, ease and intervals.
    case("getDeckStats review card", "getDeckStats", {"decks": ["Default"]}, reads=STATS_READS,
         setup=review),
    # deck_stats on a parent: the subtree's names; keyed by new deck ids, so read whole.
    case("getDeckStats subtree", "getDeckStats", {"decks": ["Japanese", "Japanese::Vocab"]},
         setup=subdeck),
    case("findCards deck:*", "findCards", {"query": "deck:*"}),
    *[case(f"findCards state {name}", "findCards", {"query": query}) for name, query in STATES.items()],
    case("findCards scoped state new", "findCards", {"query": '"deck:Default" ' + STATES["new"]}),
    case("getEaseFactors new card", "getEaseFactors", lambda c: {"cards": [c["cid"]]}),
    case("getEaseFactors review card", "getEaseFactors", lambda c: {"cards": [c["cid"]]}, setup=review),
    case("getIntervals new card", "getIntervals", lambda c: {"cards": [c["cid"]]}),
    case("getIntervals review card", "getIntervals", lambda c: {"cards": [c["cid"]]}, setup=review),
    # review_stats: without a deck every card's reviews (id, ease); with one, cardReviews tuples.
    case("getReviewsOfCards", "getReviewsOfCards", lambda c: {"cards": [c["cid"]]}, setup=review),
    case("getReviewsOfCards no reviews", "getReviewsOfCards", lambda c: {"cards": [c["cid"]]}),
    case("cardReviews", "cardReviews", {"startID": 1700000000000, "deck": "Default"}, setup=review),
    # list_decks: deckNames without params; create_deck: deckNamesAndIds without params.
    case("createDeck", "createDeck", {"deck": "Japanese::Vocab"}, effects=True),
    case("changeDeck", "changeDeck", lambda c: {"cards": [c["cid"]], "deck": "Japanese"}, effects=True),
    # Notes: add_note / add_notes check the sort field first, then match error text.
    case("modelFieldNames missing model", "modelFieldNames", {"modelName": "Vocab"}),
    case("addNote no tags or options", "addNote", add({"Front": "猫", "Back": "cat"}), effects=True),
    case("addNote tags and duplicate scope", "addNote",
         add({"Front": "猫", "Back": "cat"}, tags=["ai", "n5"], allowDuplicate=False,
             duplicateScope="deck", duplicateScopeOptions={"deckName": "Default", "checkChildren": False,
                                                           "checkAllModels": False}), effects=True),
    case("addNote duplicate", "addNote", add({"Front": "犬", "Back": "dog"})),
    case("addNote duplicate in deck scope", "addNote",
         add({"Front": "犬", "Back": "dog"}, allowDuplicate=False, duplicateScope="deck")),
    case("addNote duplicate allowed", "addNote", add({"Front": "犬", "Back": "dog"}, allowDuplicate=True),
         effects=True),
    case("addNote missing model", "addNote", {"note": {**add({"Front": "猫"})["note"], "modelName": "Vocab"}}),
    case("addNote missing deck", "addNote", {"note": {**add({"Front": "猫"})["note"], "deckName": "Nope"}}),
    case("updateNoteFields", "updateNoteFields",
         lambda c: {"note": {"id": c["nid"], "fields": {"Back": "<b>dog</b>"}}}, reads=["error"], effects=True),
    case("findNotes bad query", "findNotes", {"query": "deck:Default ("}),
    # Models.
    case("createModel", "createModel", {"modelName": "Vocab", "inOrderFields": ["Word", "Meaning"],
                                         "cardTemplates": BASIC_TEMPLATES, "isCloze": False},
         reads=["result.id", "result.name", "error"]),
    case("createModel existing name", "createModel", {"modelName": "Basic", "inOrderFields": ["Word", "Meaning"],
                                                       "cardTemplates": BASIC_TEMPLATES, "isCloze": False}),
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
    # Tags: tags are one space-separated string.
    case("addTags", "addTags", lambda c: {"notes": [c["nid"]], "tags": "ai n5"}, reads=["error"], effects=True),
    case("replaceTags", "replaceTags",
         lambda c: {"notes": [c["nid"]], "tag_to_replace": "seeded", "replace_with_tag": "ai"},
         reads=["error"], effects=True),
    case("clearUnusedTags", "clearUnusedTags", reads=["error"]),
    # Media: storeMediaFile always sends deleteExisting.
    case("storeMediaFile data", "storeMediaFile", {"filename": "ai.png", "deleteExisting": True, "data": B64},
         effects=True),
    case("storeMediaFile path", "storeMediaFile",
         lambda c: {"filename": "ai.png", "deleteExisting": True, "path": c["png_path"]}, effects=True),
    case("retrieveMediaFile missing", "retrieveMediaFile", {"filename": "gone.png"}),
    case("getMediaFilesNames {}", "getMediaFilesNames", {}),
    case("getMediaFilesNames pattern", "getMediaFilesNames", {"pattern": "seed*"}),
    # Scheduling writes, after the existence checks above.
    case("unsuspend", "unsuspend", lambda c: {"cards": [c["cid"]]}, reads=["error"], setup=suspended),
    case("forgetCards", "forgetCards", lambda c: {"cards": [c["cid"]]}, reads=["error"], setup=review),
    case("setDueDate", "setDueDate", lambda c: {"cards": [c["cid"]], "days": "3"}, reads=["error"]),
]
