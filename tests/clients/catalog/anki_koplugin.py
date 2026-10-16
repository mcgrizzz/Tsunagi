"""Catalog entries first sent by anki.koplugin (https://github.com/Ajatt-Tools/anki.koplugin at 55b07ed):
its requests that no other entry covers (tests/clients/anki_koplugin/client.py)."""


from clients.support import B64, case, named, note, serve

WHOLE = ("",)

# conf defaults (anki_configuration.lua): allow_dupes false, dupe_scope deck; tags start with KOReader.
NO_DUPS_DECK = {"allowDuplicate": False, "duplicateScope": "deck"}

OGG = b"OggS\x00fake-ogg"

def forvo(col, ctx):
    """ctx["forvo"]: the audio server's base URL, for this case: one clip, at /ogg/inu.ogg."""
    return {"forvo": serve(ctx, lambda path: (200, OGG) if path == "/ogg/inu.ogg" else (404, b""))}

def word(c, **media):
    """A note as AnkiNote:build makes it, with set_forvo_audio's single audio object."""
    return note(fields={"Front": "猫", "Back": "cat"}, tags=["KOReader"], options=NO_DUPS_DECK,
                audio={"url": c["forvo"] + "/ogg/inu.ogg", "filename": "forvo_猫.ogg", "fields": ["Back"]},
                **media)


ENTRIES = named("anki.koplugin", [
    case("addNote forvo audio, a single object", "addNote", lambda c: {"note": word(c)},
         reads=WHOLE, effects=True, setup=forvo),
    # set_image_data: a Mokuro page, named after the book and the time.
    case("addNote forvo audio and a picture, single objects", "addNote", lambda c: {"note": word(
        c, picture={"data": B64, "filename": "Book_2026-10-16 12-00-00.jpg", "fields": ["Back"]})},
        reads=WHOLE, effects=True, setup=forvo),
    # delete_latest_note: the hand-written request, key null when no API key is set.
    case("deleteNotes key null", "deleteNotes", lambda c: {"notes": [c["nid"]]}, key=None,
         reads=WHOLE, effects=True),
])
