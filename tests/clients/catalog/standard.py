"""
Standard requests and collection states (6.135), taken from the tested
clients' cases: what most AnkiConnect clients send.

STANDARD is version 6 with params always sent, each answer and its effects
compared whole; ENVELOPES runs a few of the same requests in every envelope
clients use. The states (setup=) are for any catalog entry.
"""
from clients.support import B64, case, note, raw

# ----- Collection states, for setup= -----


def revlog(col, cid, ivl, last_ivl, factor, ease=3, kind=1, at_ms=None):
    """A review log row (kind 0 learn, 1 review), at at_ms or a fixed time."""
    col.db.execute("insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
                   "values (?, ?, -1, ?, ?, ?, ?, 6000, ?)",
                   at_ms or 1_700_000_000_000, cid, ease, ivl, last_ivl, factor, kind)


def review_card(ivl=12, due_in=0):
    """The seeded card as a review card: interval ivl days, due in due_in days, one review."""
    def setup(col, ctx):
        card = col.get_card(ctx["cid"])
        card.type = card.queue = 2
        card.ivl, card.due, card.factor, card.reps = ivl, col.sched.today + due_in, 2500, 3
        col.update_card(card)
        revlog(col, ctx["cid"], ivl, 4, 2500)
    return setup


def learning_card(col, ctx):
    """The seeded card in learning after one answer: its revlog interval is negative seconds."""
    card = col.get_card(ctx["cid"])
    card.type = card.queue = 1
    card.due, card.left, card.reps = 1_700_000_600, 1001, 1
    col.update_card(card)
    revlog(col, ctx["cid"], -600, 0, 0, kind=0)


def suspended(col, ctx):
    col.sched.suspend_cards([ctx["cid"]])


def deck(name):
    """A deck that exists before the request."""
    return lambda col, ctx: {"did": col.decks.id(name)}


def in_deck(name):
    """The seeded card moved into deck name (made if needed)."""
    def setup(col, ctx):
        did = col.decks.id(name)
        col.set_deck([ctx["cid"]], did)
        return {"did": did}
    return setup


def second_note(front="猫", back="cat", deck_name="Default"):
    """Another Basic note: ctx nid2 and cid2."""
    def setup(col, ctx):
        n = col.new_note(col.models.by_name("Basic"))
        n["Front"], n["Back"] = front, back
        col.add_note(n, col.decks.id(deck_name))
        return {"nid2": n.id, "cid2": col.card_ids_of_note(n.id)[0]}
    return setup


# ----- Standard requests -----

WHOLE = ("",)
NEW = note(fields={"Front": "猫", "Back": "cat"})


def _std(name, action, params=None, **kw):
    return case(name, action, {} if params is None else params, reads=WHOLE, **kw)


STANDARD = [
    # Connection and names (settings pages).
    _std("version", "version"),
    _std("requestPermission", "requestPermission"),
    _std("deckNames", "deckNames"),
    _std("deckNames with a subdeck", "deckNames", setup=deck("Default::Sub")),
    _std("deckNamesAndIds", "deckNamesAndIds"),
    _std("modelNames", "modelNames"),
    _std("modelNamesAndIds", "modelNamesAndIds"),
    _std("modelFieldNames", "modelFieldNames", {"modelName": "Basic"}),
    _std("modelFieldNames missing model", "modelFieldNames", {"modelName": "Nope"}),
    # Finding notes and cards.
    _std("findNotes deck", "findNotes", {"query": "deck:Default"}),
    _std("findNotes everything", "findNotes", {"query": "deck:*"}),
    _std("findNotes empty query", "findNotes", {"query": ""}),
    _std("findNotes newest (added:1)", "findNotes", {"query": "added:1"}),
    _std("findNotes field value", "findNotes", {"query": '"Front:犬"'}),
    _std("findNotes nid list", "findNotes", lambda c: {"query": f"nid:{c['nid']},{c['nid2']}"},
         setup=second_note()),
    _std("findNotes bad query", "findNotes", {"query": "prop:nope"}),
    _std("findCards deck", "findCards", {"query": "deck:Default"}),
    _std("findCards new", "findCards", {"query": "is:new"}),
    _std("findCards review", "findCards", {"query": "-is:new -is:learn"}, setup=review_card()),
    _std("findCards due today", "findCards", {"query": "prop:due<=0"}, setup=review_card()),
    # Reading notes and cards.
    _std("notesInfo", "notesInfo", lambda c: {"notes": [c["nid"]]}),
    _std("notesInfo with a missing id", "notesInfo", lambda c: {"notes": [c["nid"], 12345]}),
    _std("notesInfo -1", "notesInfo", {"notes": [-1]}),
    _std("notesModTime", "notesModTime", lambda c: {"notes": [c["nid"]]}),
    _std("cardsInfo new card", "cardsInfo", lambda c: {"cards": [c["cid"]]}),
    _std("cardsInfo review card", "cardsInfo", lambda c: {"cards": [c["cid"]]}, setup=review_card()),
    _std("cardsInfo learning card", "cardsInfo", lambda c: {"cards": [c["cid"]]}, setup=learning_card),
    _std("cardsInfo with a missing id", "cardsInfo", lambda c: {"cards": [c["cid"], 12345]}),
    _std("cardsModTime with a missing id", "cardsModTime", lambda c: {"cards": [c["cid"], 12345]}),
    _std("areSuspended", "areSuspended", lambda c: {"cards": [c["cid"], 12345]}, setup=suspended),
    _std("getIntervals two new cards", "getIntervals",
         lambda c: {"cards": [c["cid"], c["cid2"]]}, setup=second_note()),
    _std("getIntervals review card", "getIntervals", lambda c: {"cards": [c["cid"]]}, setup=review_card()),
    _std("getIntervals learning card", "getIntervals", lambda c: {"cards": [c["cid"]]}, setup=learning_card),
    _std("getEaseFactors", "getEaseFactors", lambda c: {"cards": [c["cid"]]}, setup=review_card()),
    _std("getReviewsOfCards", "getReviewsOfCards", lambda c: {"cards": [c["cid"]]}, setup=review_card()),
    _std("getDecks", "getDecks", lambda c: {"cards": [c["cid"]]}, setup=in_deck("Default::Sub")),
    _std("getDeckStats", "getDeckStats", {"decks": ["Default"]}),
    _std("getDeckConfig", "getDeckConfig", {"deck": "Default"}),
    _std("getDeckConfig missing deck", "getDeckConfig", {"deck": "Nope"}),
    _std("getTags", "getTags"),
    # Adding notes.
    _std("addNote", "addNote", {"note": NEW}, effects=True),
    _std("addNote allowDuplicate", "addNote", {"note": {**note(), "options": {"allowDuplicate": True}}},
         effects=True),
    _std("addNote duplicate", "addNote", {"note": {**note(), "options": {"allowDuplicate": False}}}),
    _std("addNote duplicate, deck scope, other deck", "addNote", {"note": {
        **note(deckName="Default::Sub"), "options": {"allowDuplicate": False, "duplicateScope": "deck"}}},
        setup=deck("Default::Sub"), effects=True),
    _std("addNote missing deck", "addNote", {"note": note(deckName="Nope")}),
    _std("addNote missing model", "addNote", {"note": note(modelName="Nope")}),
    _std("addNote empty first field", "addNote", {"note": note(fields={"Front": "", "Back": "x"})}),
    _std("addNote picture by data", "addNote", {"note": {**NEW, "picture": [
        {"data": B64, "filename": "pic.png", "fields": ["Back"]}]}}, effects=True),
    _std("addNote picture by path", "addNote", lambda c: {"note": {**NEW, "picture": [
        {"path": c["png_path"], "filename": "pic.png", "fields": ["Back"]}]}}, effects=True),
    _std("addNote audio with empty media lists", "addNote", {"note": {
        **NEW, "audio": [], "picture": [], "video": []}}, effects=True),
    _std("canAddNotes", "canAddNotes", {"notes": [note(), NEW]}),
    _std("canAddNotesWithErrorDetail", "canAddNotesWithErrorDetail",
         {"notes": [note(), NEW, note(fields={"Front": "", "Back": "x"})]}),
    _std("addNotes", "addNotes", {"notes": [NEW, note(fields={"Front": "鳥", "Back": "bird"})]}, effects=True),
    _std("addNotes with an empty note", "addNotes",
         {"notes": [NEW, note(fields={"Front": "", "Back": "x"})]}, effects=True),
    # Changing notes.
    _std("updateNoteFields", "updateNoteFields",
         lambda c: {"note": {"id": c["nid"], "fields": {"Back": "dog!"}}}, effects=True),
    _std("updateNoteFields missing note", "updateNoteFields",
         {"note": {"id": 12345, "fields": {"Back": "x"}}}),
    _std("updateNoteFields picture replacing a field", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Back": ""}, "picture": [
            {"data": B64, "filename": "pic.png", "fields": ["Back"]}]}}, effects=True),
    _std("addTags", "addTags", lambda c: {"notes": [c["nid"]], "tags": "a b"}, effects=True),
    _std("removeTags", "removeTags", lambda c: {"notes": [c["nid"]], "tags": "seeded"}, effects=True),
    _std("deleteNotes", "deleteNotes", lambda c: {"notes": [c["nid"]]}, effects=True),
    _std("deleteNotes []", "deleteNotes", {"notes": []}, effects=True),
    _std("suspend", "suspend", lambda c: {"cards": [c["cid"]]}, effects=True),
    _std("unsuspend", "unsuspend", lambda c: {"cards": [c["cid"]]}, setup=suspended, effects=True),
    # Decks.
    _std("createDeck", "createDeck", {"deck": "New::Deck"}, effects=True),
    _std("createDeck existing", "createDeck", {"deck": "Default"}, effects=True),
    _std("changeDeck to a new deck", "changeDeck", lambda c: {"cards": [c["cid"]], "deck": "Moved"},
         effects=True),
    _std("deleteDecks", "deleteDecks", {"decks": ["Old"], "cardsToo": True}, setup=deck("Old"), effects=True),
    _std("deleteDecks [] cardsToo", "deleteDecks", {"decks": [], "cardsToo": True}, effects=True),
    # Note types.
    _std("createModel", "createModel", {"modelName": "Mined", "inOrderFields": ["Word", "Meaning"],
         "cardTemplates": [{"Name": "Card 1", "Front": "{{Word}}", "Back": "{{Meaning}}"}]}, effects=True),
    _std("createModel existing name", "createModel", {"modelName": "Basic", "inOrderFields": ["A"],
         "cardTemplates": [{"Front": "{{A}}", "Back": "{{A}}"}]}),
    _std("modelStyling", "modelStyling", {"modelName": "Basic"}),
    # Media.
    _std("storeMediaFile data", "storeMediaFile", {"filename": "a.png", "data": B64}, effects=True),
    _std("storeMediaFile path", "storeMediaFile", lambda c: {"filename": "a.png", "path": c["png_path"]},
         effects=True),
    _std("storeMediaFile name taken, deleteExisting false", "storeMediaFile",
         {"filename": "seed-1.txt", "data": B64, "deleteExisting": False}, effects=True),
    _std("storeMediaFile full path as filename", "storeMediaFile",
         {"filename": "/tmp/app/temp/shot.png", "data": B64}, effects=True),
    _std("retrieveMediaFile", "retrieveMediaFile", {"filename": "seed-1.txt"}),
    _std("retrieveMediaFile missing", "retrieveMediaFile", {"filename": "nope.png"}),
    _std("getMediaFilesNames", "getMediaFilesNames", {"pattern": "seed-*"}),
    _std("deleteMediaFile", "deleteMediaFile", {"filename": "seed-1.txt"}, effects=True),
    # Batches.
    _std("multi, versioned actions", "multi", {"actions": [
        {"action": "deckNames", "version": 6}, {"action": "nosuchaction", "version": 6}]}),
    _std("multi, unversioned actions", "multi", {"actions": [
        {"action": "deckNames"}, {"action": "modelNames"}]}),
]


# ----- Card states -----
# The actions whose answer the Shim builds from a card's scheduling, each run
# with a card in every state a collection has. A state's setup returns
# ctx["cards"], the cards to ask about.


def _as(state):
    def setup(col, ctx):
        state(col, ctx)
        return {"cards": [ctx["cid"]]}
    return setup


def _day_learning(col, ctx):
    """In learning with a step of a day: queue 3, due on a day, not a time."""
    card = col.get_card(ctx["cid"])
    card.type, card.queue = 1, 3
    card.due, card.left, card.reps = col.sched.today, 1001, 1
    col.update_card(card)
    revlog(col, ctx["cid"], 1, 0, 0, kind=0)


def _relearning(col, ctx):
    """A review card forgotten: type 3, back in learning, one lapse."""
    card = col.get_card(ctx["cid"])
    card.type, card.queue = 3, 1
    card.due, card.left, card.ivl, card.factor = 1_700_000_600, 1001, 1, 2300
    card.reps, card.lapses = 4, 1
    col.update_card(card)
    revlog(col, ctx["cid"], 12, 4, 2500)
    revlog(col, ctx["cid"], -600, 12, 2300, ease=1, kind=2, at_ms=1_700_000_100_000)


def _buried(manual):
    return lambda col, ctx: col.sched.bury_cards([ctx["cid"]], manual=manual)


def _in_filtered_deck(col, ctx):
    """A review card due today, pulled into a filtered deck."""
    review_card()(col, ctx)
    deck = col.sched.get_or_create_filtered_deck(deck_id=0)
    deck.name = "Filtered"
    deck.config.search_terms[0].search = "deck:Default"
    col.sched.add_or_update_filtered_deck(deck)


def _fsrs(col, ctx):
    """A review card with FSRS on, and its memory state."""
    from anki.cards import FSRSMemoryState

    review_card()(col, ctx)
    col.set_config("fsrs", True)
    card = col.get_card(ctx["cid"])
    card.memory_state = FSRSMemoryState(stability=12.0, difficulty=5.0)
    col.update_card(card)


def _cloze(col, ctx):
    """A cloze note's two cards."""
    n = col.new_note(col.models.by_name("Cloze"))
    n["Text"] = "{{c1::犬}} is {{c2::dog}}"
    col.add_note(n, 1)
    return {"cards": col.card_ids_of_note(n.id)}


CARD_STATES = {
    "new": _as(lambda col, ctx: None),
    "learning": _as(learning_card),
    "day learning": _as(_day_learning),
    "review": _as(review_card()),
    "relearning": _as(_relearning),
    "suspended": _as(suspended),
    "buried": _as(_buried(True)),
    "sibling buried": _as(_buried(False)),
    "in a filtered deck": _as(_in_filtered_deck),
    "FSRS": _as(_fsrs),
    "cloze": _cloze,
}
CARD_ACTIONS = {
    "cardsInfo": lambda c: {"cards": c["cards"]},
    "getIntervals": lambda c: {"cards": c["cards"]},
    "areDue": lambda c: {"cards": c["cards"]},
    "getEaseFactors": lambda c: {"cards": c["cards"]},
    "areSuspended": lambda c: {"cards": c["cards"]},
    "getReviewsOfCards": lambda c: {"cards": c["cards"]},
    "getDeckStats": {"decks": ["Default"]},
}

STATES = [
    _std(f"{action}, {state} card", action, params, setup=setup)
    for state, setup in CARD_STATES.items()
    for action, params in CARD_ACTIONS.items()
]


# ----- Envelopes -----
# Every envelope clients use, on three requests: one that answers, one whose
# answer is an error, one with required params.

ACTIONS = ("deckNames", "addNote missing model", "notesInfo")


def _envelope_body(action, version, params, key):
    def body(c):
        given = {"deckNames": {}, "notesInfo": {"notes": [c["nid"]]},
                 "addNote missing model": {"note": note(modelName="Nope")}}[action]
        out = {"action": action.split(" ")[0]}
        if version != "absent":
            out["version"] = version
        if params == "given":
            out["params"] = given
        elif params == "null":
            out["params"] = None
        if key == "null":
            out["key"] = None
        return out
    return body


ENVELOPES = [
    raw(f"{action}: version {version}, params {params}, key {key}",
        _envelope_body(action, version, params, key))
    for action in ACTIONS
    for version in ("absent", 2, 4, 6)
    for params in ("absent", "given", "null")
    for key in ("absent", "null")
] + [
    raw(f"{action}: GET, version {version}", _envelope_body(action, version, "given", "absent"), method="GET")
    for action in ACTIONS for version in (2, 6)
]

ENVELOPE_KINDS = {"version": (2, 4, 6, "absent"), "params": ("always", "omit-when-empty", "null"),
                  "key": ("absent", "null", "configured"), "method": ("POST", "GET")}
