"""JL: Japanese pop-up dictionary (Windows), mining to Anki through AnkiConnect."""
from clients.support import B64, case, note

CLIENT = {
    "name": "JL",
    "repo": "https://github.com/rampaa/JL",
    "commit": "8995ac5",
    "read": "2026-10-15",
    "files": [
        "JL.Core/External/AnkiConnect/AnkiConnectClient.cs",
        "JL.Core/External/AnkiConnect/AnkiConnectUtils.cs",
        "JL.Core/External/AnkiConnect/AnkiConfigUtils.cs",
        "JL.Core/External/AnkiConnect/Note.cs",
        "JL.Core/External/AnkiConnect/Request.cs",
        "JL.Core/External/AnkiConnect/RequestWithParameters.cs",
        "JL.Core/External/AnkiConnect/Response.cs",
        "JL.Core/Mining/MiningUtils.cs",
        "JL.Core/Config/CoreConfigManager.cs",
    ],
    "uses": "System.Text.Json, version 6, null properties left out (no params, tags or media when unset); "
            "byte[] media data is sent as base64",
    "notes": "A non-null error string is shown verbatim and the result dropped; a non-2xx status is "
             "dropped silently. addNote's result is read with GetInt64. sync and guiBrowse aren't covered.",
}

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



# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}
USES = [
    "deckNames",
    "modelFieldNames",
    "modelFieldNames missing model",
    "modelNames",
]

CASES = [
    # Preferences (PreferencesWindow.xaml.cs L473-552; AnkiConfigUtils.cs L93, one per mine type).
    # Duplicate check per popup, first field only (MiningUtils.cs L1680-1697).
    case("canAddNotes popup first field", "canAddNotes",
         {"notes": [check("犬"), check("猫")]}),
    case("canAddNotes popup collection scope", "canAddNotes",
         {"notes": [check("犬", options=CHECK_ALL), check("猫", options=CHECK_ALL)]}),
    # Mining: one note with every field, no media, then addNote (AnkiConnectUtils.cs L200-217).
    case("canAddNotes mine", "canAddNotes", {"notes": [check("猫", "cat")]}),
    case("canAddNotes mine duplicate", "canAddNotes", {"notes": [check("犬", "dog")]}),
    case("addNote", "addNote", {"note": mined()}, effects=True),
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
]
