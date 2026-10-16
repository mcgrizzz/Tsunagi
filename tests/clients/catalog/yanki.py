"""Catalog entries first sent by Yanki (https://github.com/kitschpatrol/yanki at 60603b4):
its requests that no other entry covers (tests/clients/yanki/client.py)."""


from clients.support import case, named

BASIC = {
    "cardTemplates": [{"Back": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}", "Front": "{{Front}}",
                       "YankiNamespace": "{{YankiNamespace}}"}],
    "inOrderFields": ["Front", "Back", "YankiNamespace"],
    "modelName": "Yanki - Basic",
}


ENTRIES = named("Yanki", [
    # Notes: missing models and decks are found by their error text, then made.
    case("createModel", "createModel", BASIC, reads=["error"]),
    # updateNoteModel with the whole local note: id, plus noteId and deckName.
    case("updateNoteModel extra keys", "updateNoteModel", lambda c: {"note": {
        "id": c["nid"], "noteId": c["nid"], "deckName": "Default", "modelName": "Basic",
        "fields": {"Front": "猫", "Back": "cat"}, "tags": ["y"], "cards": [c["cid"]]}}, effects=True),
    case("updateNoteModel missing model", "updateNoteModel", lambda c: {"note": {
        "id": c["nid"], "modelName": "Yanki - Basic", "fields": {"Front": "猫", "Back": "cat"}, "tags": []}}),
    # Styling command.
    case("modelStyling missing model", "modelStyling", {"modelName": "Yanki - Basic"}),
    # Media: exists?, then store and compare the returned name.
    case("getMediaFilesNames namespace", "getMediaFilesNames", {"pattern": "yanki-media-*"}),
])
