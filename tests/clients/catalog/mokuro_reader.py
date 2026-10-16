"""Catalog entries first sent by mokuro-reader (https://github.com/Gnathonic/mokuro-reader at bfaeb48):
its requests that no other entry covers (tests/clients/mokuro_reader/client.py)."""


from clients.support import B64, case, named

PICTURE = {"filename": "mokuro_One_Piece_v01_0001.jpg", "data": B64, "fields": ["Back"]}


ENTRIES = named("mokuro-reader", [
    case("addNote picture", "addNote", {"note": {
        "deckName": "Default", "modelName": "Basic", "fields": {"Front": "犬"},
        "options": {"allowDuplicate": True}, "picture": [PICTURE], "tags": ["mining", "One_Piece"]}},
        effects=True),
    case("addNote no tags", "addNote", {"note": {
        "deckName": "Default", "modelName": "Basic", "fields": {"Front": "猫", "Back": "cat"},
        "options": {"allowDuplicate": True}, "picture": [PICTURE]}}, effects=True),
    # Update the last card (index.ts L587-606, L898-1067; TextBoxPicker.svelte L113-155).
    case("updateNoteFields picture field cleared", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Front": "犬が走る", "Back": ""}, "picture": [PICTURE]}}, effects=True),
    case("updateNoteFields picture after existing", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Front": "犬", "Back": "dog"}, "picture": [PICTURE]}}, effects=True),
])
