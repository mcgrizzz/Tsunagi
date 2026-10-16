"""Catalog entries first sent by Memento (https://github.com/ripose-jp/Memento at e45a792):
its requests that no other entry covers (tests/clients/memento/client.py)."""


from urllib.parse import parse_qs, urlsplit

from clients.support import B64, MD5, case, named, note, serve

# Default profile (ankiconfigkeys.h): duplicate policy "different deck", tag "memento".
SCOPE_DECK = {"duplicateScope": "deck"}

NO_DUPS = {"allowDuplicate": False}

ALLOW = {"allowDuplicate": True}

# setting/keys.h: JapanesePod101's URL template and no-audio clip hash.
POD_PATH = "/dictionary/japanese/audiomp3.php"

SKIP = "7e2c2f954ef6051373ba916f000168dc"

MP3 = b"ID3\x03\x00fake-mp3"

def _pod_audio(path):
    """JapanesePod101's audio, for 猫/ねこ only."""
    url = urlsplit(path)
    found = url.path == POD_PATH and parse_qs(url.query) == {"kanji": ["猫"], "kana": ["ねこ"]}
    return (200, MP3) if found else (404, b"")

def pod(col, ctx):
    """ctx["pod"]: the audio server's base URL, for this case."""
    return {"pod": serve(ctx, _pod_audio)}

def term(front="猫", back="ねこ", options=SCOPE_DECK, **over):
    """A note as Anki::Note::build makes it (notebuilder.cpp L2441-2500)."""
    return note(**{"fields": {"Front": front, "Back": back}, "tags": ["memento"], "options": options, **over})

def pod_audio(c, kanji="猫", kana="ねこ"):
    """The {audio} entry (notebuilder.cpp createAudio L2266-2296)."""
    return {"url": c["pod"] + f"{POD_PATH}?kanji={kanji}&kana={kana}",
            "filename": f"memento_JapanesePod101_{kana}_{kanji}.mp3",
            "fields": ["Back"], "skipHash": SKIP}

def store(name):
    """One storeMediaFile of addMedia's multi (ankiclient.cpp L435-450): no version."""
    return {"action": "storeMediaFile", "params": {"data": B64, "filename": name}}

EVERYTHING = ("",)

def other_deck(col, ctx):
    col.decks.id("Other")


ENTRIES = named("Memento", [
    # Settings: test connection, then decks, models, fields (ankiclient.cpp L103-234).
    # Can it be added: the expression, then the reading as the expression (L241-297).
    case("canAddNotes term", "canAddNotes",
         {"notes": [term("犬", "いぬ"), term("いぬ", "いぬ")]}, reads=EVERYTHING),
    case("canAddNotes term, any deck", "canAddNotes",
         {"notes": [term("犬", "いぬ", NO_DUPS, deckName="Other")]}, reads=EVERYTHING, setup=other_deck),
    case("canAddNotes term, duplicates allowed", "canAddNotes",
         {"notes": [term("犬", "いぬ", ALLOW)]}, reads=EVERYTHING),
    # Dictionary images first, named by their MD5 (glossarybuilder.cpp L853-877).
    case("multi storeMediaFile", "multi",
         {"actions": [store(MD5 + ".png"), store("0f343b0931126a20f133d67c2b018a3b.gif")]},
         reads=EVERYTHING, effects=True),
    # Then the note (ankiclient.cpp L406-433).
    case("addNote", "addNote", {"note": term()}, reads=EVERYTHING, effects=True),
    # Issue #353: the {audio} URL and filename in Japanese.
    case("addNote audio url in Japanese", "addNote", lambda c: {"note": term(audio=[pod_audio(c)])},
         reads=EVERYTHING, effects=True, setup=pod),
    # {audio-media}, {screenshot} and {video}: data named by MD5 (notebuilder.cpp L731-870).
    case("addNote clip, screenshot and video", "addNote", {"note": term(
        audio=[{"data": B64, "filename": MD5 + ".aac", "fields": ["Back"]}],
        picture=[{"data": B64, "filename": MD5 + ".jpg", "fields": ["Back"]}],
        video=[{"data": B64, "filename": MD5 + ".mp4", "fields": ["Back"]}])},
        reads=EVERYTHING, effects=True),
])
