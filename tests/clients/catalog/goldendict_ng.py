"""Catalog entries first sent by GoldenDict-ng (https://github.com/xiaoyifang/goldendict-ng at 5b1bade):
its requests that no other entry covers (tests/clients/goldendict_ng/client.py)."""


from clients.support import B64, case, named, serve

MP3 = b"ID3\x03\x00fake-mp3"

READS = ("",)

def sent(fields, audio=()):
    """addNote's note as the template in ankiconnector.cc sendToAnki (L63-78) fills it."""
    return {"note": {"deckName": "Default", "modelName": "Basic", "fields": fields,
                     "audio": list(audio), "options": {"allowDuplicate": True}, "tags": []}}

def clip(filename):
    """Audio the dictionary served, base64 (articleview.cc buildAnkiAudioDataObject L84-111)."""
    return {"data": B64, "filename": filename, "fields": ["Back"]}

def web_audio(col, ctx):
    """ctx["audio"]: a web audio link, for this case."""
    return {"audio": serve(ctx, lambda path: (200, MP3) if path == "/cat.mp3" else (404, b""))}


ENTRIES = named("GoldenDict-ng", [
    # The word already has a note: duplicates are always allowed.
    case("addNote", "addNote", sent({"Front": "犬", "Back": "dog<br>a domestic animal"}),
         reads=READS, effects=True),
    # The default field names (config.cc L52-61), none of them Basic's.
    case("addNote default field names", "addNote",
         sent({"word": "猫", "selected_text": "cat", "marked_sentence": "<b>猫</b>"}), reads=READS),
    case("addNote empty field", "addNote", sent({"Front": "猫", "Back": ""}), reads=READS, effects=True),
    case("addNote audio data", "addNote",
         sent({"Front": "猫", "Back": "cat"}, [clip("猫_1700000000000.mp3")]), reads=READS, effects=True),
    case("addNote audio data, slash in the word", "addNote",
         sent({"Front": "AC/DC", "Back": "band"}, [clip("AC/DC_1700000000000.mp3")]),
         reads=READS, effects=True),
    case("addNote audio url", "addNote", lambda c: sent({"Front": "猫", "Back": "cat"}, [
        {"url": c["audio"] + "/cat.mp3", "filename": "猫_1700000000000.mp3", "fields": ["Back"]}]),
        reads=READS, effects=True, setup=web_audio),
])
