"""Catalog entries first sent by JL (https://github.com/rampaa/JL at 8995ac5):
its requests that no other entry covers (tests/clients/jl/client.py)."""


from clients.support import B64, case, named, note

# CoreConfigManager.cs ApplyPreferences: every option is false by default.
SCOPE = {"checkChildren": False, "checkAllModels": False}

CHECK = {"allowDuplicate": False, "duplicateScope": "deck", "duplicateScopeOptions": SCOPE}

# Every option on: duplicates allowed, the whole collection, children and all note types.
CHECK_ALL = {"allowDuplicate": False, "duplicateScope": "collection",
             "duplicateScopeOptions": {"checkChildren": True, "checkAllModels": True}}

ADD_ALL = {**CHECK_ALL, "allowDuplicate": True}

# NetworkUtils.cs: JapanesePod101's no-audio clip, uppercase (upstream compares lowercase).
SKIP = "7E2C2F954EF6051373BA916F000168DC"

def check(front, back=None, options=CHECK):
    """A note as canAddNotes gets it: no tags, no media (Note.cs; AnkiConnectUtils.cs L200)."""
    fields = {"Front": front} if back is None else {"Front": front, "Back": back}
    return {"deckName": "Default", "modelName": "Basic", "fields": fields, "options": options}

def mined(**over):
    """A note as addNote gets it after the check (AnkiConnectUtils.cs L216-217)."""
    return note(**{"fields": {"Front": "猫", "Back": "cat"}, "tags": ["JL"], "options": CHECK, **over})

def audio(kind, fields):
    return {"data": B64, "filename": f"JL_{kind}_ねこ_猫.mp3", "skipHash": SKIP, "fields": fields}


ENTRIES = named("JL", [
    # Preferences (PreferencesWindow.xaml.cs L473-552; AnkiConfigUtils.cs L93, one per mine type).
    # Duplicate check per popup, first field only (MiningUtils.cs L1680-1697).
    case("canAddNotes popup first field", "canAddNotes",
         {"notes": [check("犬"), check("猫")]}),
    case("canAddNotes popup collection scope", "canAddNotes",
         {"notes": [check("犬", options=CHECK_ALL), check("猫", options=CHECK_ALL)]}),
    case("addNote duplicate allowed", "addNote",
         {"note": mined(fields={"Front": "犬", "Back": "dog"}, options=ADD_ALL)}, effects=True),
    case("addNote missing deck", "addNote", {"note": mined(deckName="JL")}),
    # Word, sentence and source-text audio, uppercase skipHash (AnkiConnectUtils.cs L415-494).
    case("addNote audio x3 uppercase skipHash", "addNote", {"note": mined(audio=[
        audio("audio", ["Back"]), audio("sentence_audio", ["Back"]),
        audio("source_text_audio", ["Front", "Back"])])}, effects=True),
    # Screenshot by data, dictionary images by local path (AnkiConnectUtils.cs L287-333).
    case("addNote picture data and path", "addNote", lambda c: {"note": mined(picture=[
        {"data": B64, "filename": "JL_SS_ねこ_猫.jpg", "fields": ["Back"]},
        {"path": c["png_path"], "filename": "JL_definitions_image_0_ねこ_猫.png", "fields": ["Back"]},
    ])}, effects=True),
])
