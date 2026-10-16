"""Catalog entries first sent by Flashcards (Obsidian) (https://github.com/reuseman/flashcards-obsidian at 2ca53d0):
its requests that no other entry covers (tests/clients/flashcards_obsidian/client.py)."""


from clients.support import case, named

NOTE_READS = ["result[*].noteId", "result[*].cards", "result[*].fields", "result[*].modelName",
              "result[*].tags", "error"]

ENTRIES = named("Flashcards (Obsidian)", [
    # execute-sync-plan.ts: no default tags, a card with an empty field (Context when it has none).
    case("addNote no tags, empty field", "addNote",
         {"note": {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "猫", "Back": ""},
                   "tags": []}}, effects=True),
    # sync-execution-session.ts: the managed cloze note type (render-card.ts getAnkiModelSpecs).
    case("createModel cloze with css", "createModel", {
        "modelName": "Obsidian-cloze", "inOrderFields": ["Text", "Extra", "Context", "Source"],
        "isCloze": True, "css": ".card { font-family: arial; }",
        "cardTemplates": [{"Name": "Card 1", "Front": "{{cloze:Text}}", "Back": "{{cloze:Text}}<br>{{Extra}}"}]},
        reads=["error"], effects=True),
    # A card's kind changed (basic to reversed): updateNoteModel, then notesInfo for the new card ids.
    case("updateNoteModel to a two-card type", "updateNoteModel", lambda c: {"note": {
        "id": c["nid"], "modelName": "Basic (and reversed card)", "fields": {"Front": "犬", "Back": ""},
        "tags": ["obsidian"]}}, reads=["error"], effects=True,
        then=(case("notesInfo after", "notesInfo", lambda c: {"notes": [c["nid"]]}, reads=NOTE_READS),)),
])
