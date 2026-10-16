"""Catalog entries first sent by Manatan (https://github.com/KolbyML/Manatan at 92d3787):
its requests that no other entry covers (tests/clients/manatan/client.py)."""


from clients.support import B64, case, named, note, serve

EVERYTHING = ("",)

MP3 = b"ID3\x03\x00fake-mp3"

def keep(dup, scope):
    """anki.ts addNote's options: allowDuplicate, and the duplicate scope setting as it is."""
    return {"allowDuplicate": dup, "duplicateScope": scope}

def mined(options=None, **over):
    """A note as DictionaryView's addNoteToAnki sends it: tag manatan."""
    return {"note": note(**{"tags": ["manatan"], "options": options or keep(False, "deck"), **over})}

def other_deck(col, ctx):
    col.decks.id("Other")

def audio_server(col, ctx):
    """ctx["audio"]: a word audio source serving /word.mp3, for this case."""
    return {"audio": serve(ctx, lambda path: (200, MP3) if path == "/word.mp3" else (404, b""))}

def image(name="manatan_card_1.webp", field="Back"):
    return {"data": B64, "filename": name, "fields": [field]}

def word_audio(c):
    """wordAudio.ts getWordAudioFilename: manatan_word_<time>.<extension of the URL>."""
    return {"url": c["audio"] + "/word.mp3", "filename": "manatan_word_1.mp3", "fields": ["Back"]}

CLIP = {"data": B64, "filename": "manatan_sentence_1.webm", "fields": ["Back"]}

WORD = {"Front": "猫", "Back": ""}


ENTRIES = named("Manatan", [
    # The lookup's duplicate check (DictionaryView checkStatus): deck, note type, target field.
    case("findNotes duplicate check", "findNotes", {"query": 'deck:"Default" note:"Basic" "Front:犬"'},
         reads=EVERYTHING),
    # addNote with each scope setting: 'deck-root' is sent as it is.
    case("addNote duplicate in another deck, collection scope", "addNote",
         mined(keep(False, "collection"), deckName="Other"), reads=EVERYTHING, setup=other_deck),
    case("addNote duplicate allowed, collection scope", "addNote", mined(keep(True, "collection")),
         reads=EVERYTHING, effects=True),
    case("addNote duplicate in another deck, deck-root scope", "addNote",
         mined(keep(False, "deck-root"), deckName="Other"), reads=EVERYTHING, setup=other_deck),
    case("addNote duplicate allowed, deck-root scope", "addNote", mined(keep(True, "deck-root")),
         reads=EVERYTHING, effects=True),
    # The page image as webp data, and the word audio by URL into its empty field.
    case("addNote page image", "addNote", mined(fields={"Front": "猫", "Back": "cat"}, picture=[image()]),
         reads=EVERYTHING, effects=True),
    case("addNote image and word audio", "addNote",
         lambda c: mined(fields=WORD, picture=[image()], audio=[word_audio(c)]),
         reads=EVERYTHING, effects=True, setup=audio_server),
    # AnimeVideoPlayer: the frame, the word audio and the sentence clip.
    case("addNote frame, word audio and sentence clip", "addNote",
         lambda c: mined(fields=WORD, picture=[image()], audio=[word_audio(c), CLIP]),
         reads=EVERYTHING, effects=True, setup=audio_server),
    # updateLastCard: media as one object, not a list.
    case("updateNoteFields sentence and picture object", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Front": "犬です", "Back": ""}, "picture": image("manatan_1.webp")}},
        reads=EVERYTHING, effects=True),
    case("updateNoteFields picture and audio objects", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Back": ""}, "picture": image("manatan_1.webp"),
        "audio": {"data": B64, "filename": "manatan_audio_1.webm", "fields": ["Back"]}}},
        reads=EVERYTHING, effects=True),
    # DictionaryView's overwrite: the picture an object, the word audio a list.
    case("updateNoteFields overwrite with image and word audio", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Front": "犬", "Back": ""}, "picture": image(),
        "audio": [word_audio(c)]}}, reads=EVERYTHING, effects=True, setup=audio_server),
])
