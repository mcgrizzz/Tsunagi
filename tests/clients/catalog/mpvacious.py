"""Catalog entries first sent by mpvacious (https://github.com/Ajatt-Tools/mpvacious at 26e4102):
its requests that no other entry covers (tests/clients/mpvacious/client.py)."""


from clients.support import case, named, note

WHOLE = ("",)

# make_add_note_request (ankiconnect.lua L199-216): the default allow_duplicates and scope.
ALLOW_DECK = {"allowDuplicate": True, "duplicateScope": "deck"}

# construct_note_fields with the default templates; the media files are already in the folder.
MINED = {"Front": "犬", "Back": '犬が走る<img alt="snapshot" src="dog_0.webp">[sound:dog_0.ogg]'}


ENTRIES = named("mpvacious", [
    # Before encoding: the first field of the note type, then the media folder (create_export_media).
    case("findModelsByName", "findModelsByName", {"modelNames": ["Basic"]}, reads=WHOLE),
    case("findModelsByName missing note type", "findModelsByName",
         {"modelNames": ["Japanese sentences"]}, reads=WHOLE),
    # The path differs between collections: only its type is compared.
    case("getMediaDirPath", "getMediaDirPath", reads=("result~type", "error")),
    # create_deck: changeDeck of no cards to make the deck.
    case("changeDeck no cards, new deck", "changeDeck", {"cards": [], "deck": "Learning"},
         reads=WHOLE, effects=True),
    # The default note: a duplicate of the seeded one allowed, the default tag "subs2srs %n" as one tag.
    case("addNote duplicate allowed, deck scope, tag with a space", "addNote", {"note": note(
        fields=MINED, tags=["subs2srs Some_Show_01"], options=ALLOW_DECK)}, reads=WHOLE, effects=True),
    case("addNote no tag", "addNote", {"note": note(fields=MINED, tags=[], options=ALLOW_DECK)},
         reads=WHOLE, effects=True),
    # new_note_checker.lua: notes added today of the configured note type and deck.
    case("findNotes added today, note type and deck", "findNotes",
         {"query": 'added:1 "note:Basic" "deck:Default"'}, reads=WHOLE),
    # append_media: the joined fields, an empty one stays "".
    case("updateNoteFields an empty field", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Front": "犬<br>犬が走る[sound:dog_0.ogg]", "Back": ""}}},
        reads=WHOLE, effects=True),
])
