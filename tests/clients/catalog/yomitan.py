"""Catalog entries first sent by Yomitan (https://github.com/yomidevs/yomitan at e7334a9):
its requests that no other entry covers (tests/clients/yomitan/client.py)."""


from clients.support import case, named

V = 2

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


ENTRIES = named("Yomitan", [
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
    # Duplicate details when tags/flags are shown or overwrite is on (backend.js L740-774).
    # {} (not null) for an unknown id: a null row throws in _normalizeNoteInfoArray.
    case("cardsInfo []", "cardsInfo", {"cards": []}, version=V, reads=[""]),
    case("addNote duplicate allowed", "addNote", {"note": ynote()}, version=V, reads=[""],
         effects=True),
    case("addNote deck-root", "addNote",
         {"note": ynote(front="猫", back="cat", deck="Default::Sub", scope="deck",
                        scope_options=DECK_ROOT)},
         version=V, reads=[""], effects=True, setup=lambda col, c: col.decks.id("Default::Sub")),
    # Overwrite: the whole new note plus id (display-anki.js L866-892).
    case("updateNoteFields whole note plus id", "updateNoteFields",
         lambda c: {"note": {**ynote(front="犬", back="dog; hound"), "id": c["nid"]}},
         version=V, reads=[""], effects=True),
    # Deck generator (anki-deck-generator-controller.js L362-372).
    case("addNotes", "addNotes",
         {"notes": [ynote(front="猫", back="cat"), ynote(front="鳥", back="bird")]},
         version=V, reads=[""], effects=True),
    case("addNotes one empty", "addNotes",
         {"notes": [ynote(front="猫", back="cat"), ynote(front="", back="x")]},
         version=V, reads=[""], effects=True),
])
