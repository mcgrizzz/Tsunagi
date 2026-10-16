"""Catalog entries first sent by asbplayer (https://github.com/asbplayer/asbplayer at 62c4d6e):
its requests that no other entry covers (tests/clients/asbplayer/client.py)."""


from clients.support import B64, case, named, note

OPTIONS = {"allowDuplicate": True, "duplicateScope": "deck",
           "duplicateScopeOptions": {"deckName": "Default", "checkChildren": False}}

AUDIO = {"filename": "asbp_Show_ep01_83400.mp3", "data": B64, "fields": ["Back"]}

PICTURE = {"filename": "asbp_Show_ep01_83400.jpeg", "data": B64, "fields": ["Back"]}


ENTRIES = named("asbplayer", [
    # Connection (AnkiSettingsTab.tsx L199-226): the app asks permission, the extension sends version;
    # requiresApiKey reads requireApikey, requireApiKey and the error text (anki.ts L491-497).
    # The setup tutorial's default deck and note type (AnkiSettingsTab.tsx L35-79, L359-389).
    case("createDeck Sentences", "createDeck", {"deck": "Sentences"}, reads=["error"], effects=True),
    case("createModel Sentence Card", "createModel", {
        "modelName": "Sentence Card",
        "inOrderFields": ["Sentence", "Word", "Definition", "Image", "Audio", "Source", "URL"],
        "css": ".card {\n  font-family: arial;\n  font-size: 20px;\n  text-align: center;\n  color: white;\n"
               "  background-color: black;\n}\n\n.image {\n  width: auto;\n  height: auto;\n"
               "  max-width: 500px;\n  max-height: 500px;\n  margin-left: auto;\n  margin-right: auto;\n}\n\n"
               ".front {\n  font-size: 30px;\n}",
        "cardTemplates": [{"Front": '<div class="front">{{Sentence}}</div>',
                           "Back": '<div class="front">{{Sentence}}</div>\n<hr id=answer>\n{{Definition}}\n'
                                   '<p/>\n<div class="image">\n{{Image}}\n</div>\n<p/>\n{{Audio}}\n<p/>\n'
                                   '{{Source}}\n<p/>\n{{URL}}'}],
    }, reads=["error"]),
    # Export (anki.ts L538-612): duplicates allowed, deck scope; audio and picture inline.
    case("addNote audio and picture", "addNote", {"note": {
        **note(fields={"Front": "犬が走る", "Back": "Show ep01 (00:01:23.4)"}, tags=["asbplayer"]),
        "options": OPTIONS, "audio": AUDIO, "picture": PICTURE}}, effects=True),
    case("addNote missing deck", "addNote", {"note": {
        **note(deckName="Mining", tags=[]), "options": OPTIONS}}),
    case("updateNoteFields whole note", "updateNoteFields", lambda c: {"note": {
        **note(fields={"Front": "犬が<b>走る</b>", "Back": '<img src="asbp_Show_ep01_83400_Ab3dE6gh.jpeg">'},
               tags=["asbplayer"]),
        "options": OPTIONS, "id": c["nid"]}}, effects=True),
    case("findNotes word escaped", "findNotes", {"query": '"Front:a\\_b\\*c\\:d"'}),
    case("cardsModTime", "cardsModTime", lambda c: {"cards": [c["cid"]]}, reads=["result[*].cardId", "error"]),
])
