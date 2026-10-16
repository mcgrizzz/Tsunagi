"""Catalog entries first sent by Online Dictionary Helper (https://github.com/ninja33/ODH at d9b7bf8):
its requests that no other entry covers (tests/clients/odh/client.py)."""


from clients.support import case, named, serve

MP3 = b"ID3\x03\x00fake-mp3"

READS = ("",)

def formatted(fields, tags=("ODH",), **more):
    """addNote's note as serviceworker.js formatNote (L113-150) builds it."""
    return {"note": {"deckName": "Default", "modelName": "Basic", "options": {"allowDuplicate": True},
                     "fields": fields, "tags": list(tags), **more}}

def dictionary_audio(col, ctx):
    """ctx["audio"]: the dictionary's audio server, for this case."""
    return {"audio": serve(ctx, lambda path: (200, MP3) if path == "/cat.mp3" else (404, b""))}


ENTRIES = named("Online Dictionary Helper", [
    case("addNote no tags, empty field", "addNote", formatted({"Front": "猫", "Back": ""}, tags=()),
         reads=READS, effects=True),
    # The audio field (Back) emptied, one audio object, the word URI-encoded in its name.
    case("addNote audio object", "addNote", lambda c: formatted({"Front": "猫", "Back": ""}, audio={
        "url": c["audio"] + "/cat.mp3", "filename": "ODH_encn_Cambridge_%E7%8C%AB_0.mp3",
        "fields": ["Back"]}), reads=READS, effects=True, setup=dictionary_audio),
])
