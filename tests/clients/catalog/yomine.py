"""Catalog entries first sent by Yomine (https://github.com/mcgrizzz/Yomine at 7044efc):
its requests that no other entry covers (tests/clients/yomine/client.py)."""


from clients.support import B64, case, named

# addNote's audio/picture items: the Attachment struct (kind skipped), always both lists.
CLIP = {"filename": "yomine-0123456789abcdef.mp3", "data": B64, "fields": ["Back"]}

SHOT = {"filename": "yomine-fedcba9876543210.png", "data": B64, "fields": ["Back"]}

def mined(fields, *, audio=(), picture=(), deck="Default", model="Basic", tags=("yomine",)):
    return {"note": {"deckName": deck, "modelName": model, "fields": fields, "tags": list(tags),
                     "audio": list(audio), "picture": list(picture),
                     "options": {"allowDuplicate": False}}}


ENTRIES = named("Yomine", [
    # Detection when /v1/health isn't Tsunagi's (client.rs detect), and every sync's profile.
    case("getActiveProfile", "getActiveProfile"),
    case("addNote no media", "addNote", mined({"Front": "猫", "Back": "cat"},
                                               tags=("yomine", "yomine::no-media")), effects=True),
    case("addNote with audio and picture", "addNote",
         mined({"Front": "猫", "Back": "cat"}, audio=[CLIP], picture=[SHOT]), effects=True),
])
