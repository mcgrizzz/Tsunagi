"""Catalog entries first sent by LunaTranslator (https://github.com/HIllya51/LunaTranslator at 0ee08c6):
its requests that no other entry covers (tests/clients/lunatranslator/client.py)."""


from clients.support import case, named

GET = {"method": "GET", "reads": [""]}

# static_data.json model_fileds: the note type LunaTranslator creates.
FIELDS = ["word", "rubytextHtml", "example_sentence", "audio_for_word", "audio_for_example_sentence",
          "screenshot", "remarks", "dictionaryInfo", "dictionaryContent", "luna_reserved_1",
          "luna_reserved_2", "luna_reserved_3", "user_custom_1", "user_custom_2", "user_custom_3"]

# htmlcode/anki/{front,back}.html and style.css, cut to the fields they use.
FRONT = "<div class=\"word\">{{ word }}</div>{{audio_for_word}}"

BACK = ("{{FrontSide}}<hr id=answer>{{ rubytextHtml }}{{example_sentence}}{{audio_for_example_sentence}}"
        "{{screenshot}}{{remarks}}<script>var info = {{ dictionaryInfo }};"
        " var content = {{ dictionaryContent }};</script>")

CSS = ".card { font-family: arial; font-size: 20px; text-align: center; }"

MODEL = {"modelName": "modelofluna", "inOrderFields": FIELDS, "css": CSS, "isCloze": False,
         "cardTemplates": [{"Name": "LUNACARDTEMPLATE1", "Front": FRONT, "Back": BACK}]}

def luna_model(col, ctx):
    """The note type and deck an earlier add left behind."""
    mm = col.models
    m = mm.new("modelofluna")
    for name in FIELDS:
        mm.add_field(m, mm.new_field(name))
    t = mm.new_template("LUNACARDTEMPLATE1")
    t["qfmt"], t["afmt"] = FRONT, BACK
    mm.add_template(m, t)
    m["css"] = CSS
    mm.add(m)
    col.decks.id("lunadeck")

def luna_note(col, ctx):
    """An earlier add of 犬."""
    luna_model(col, ctx)
    n = col.new_note(col.models.by_name("modelofluna"))
    n["word"] = "犬"
    col.add_note(n, col.decks.id("lunadeck"))

# showword.py loadfileds: the text fields of one lookup.
TEXT_FIELDS = {
    "word": "犬",
    "rubytextHtml": "<ruby>犬<rt>いぬ</rt></ruby>",
    "dictionaryContent": '{"mdict": "%3Cdiv%3Edog%3C/div%3E"}',
    "dictionaryInfo": '[{"dict": "mdict", "name": "MDict"}]',
    "example_sentence": "犬が<b>好き</b>。<br>二行目",
    "remarks": "",
}

def luna_add(fields=TEXT_FIELDS, allow_duplicate=True, picture=()):
    """ankiconnect.py Note.add: audio, picture and video are always sent, empty when unused."""
    def params(c):
        return {"note": {"deckName": "lunadeck", "modelName": "modelofluna", "fields": fields,
                         "options": {"allowDuplicate": allow_duplicate}, "tags": [],
                         "audio": [], "picture": [dict(p, path=c["png_path"]) for p in picture],
                         "video": []}}
    return params

SCREENSHOT = {"filename": "3f2c8a8e-2d1b-4c8e-9a51-0f6d2b7c4e11.png", "fields": ["screenshot"]}


ENTRIES = named("LunaTranslator", [
    # Then the note type; its exact error text means it is already there.
    case("createModel", "createModel", MODEL, setup=lambda col, c: col.decks.id("lunadeck"), **GET),
    # The note; its id is kept to delete it if the same word is added again.
    case("addNote", "addNote", luna_add(), setup=luna_model, effects=True, **GET),
    case("addNote screenshot by path", "addNote", luna_add(picture=[SCREENSHOT]),
         setup=luna_model, effects=True, **GET),
    case("addNote duplicate refused", "addNote", luna_add(allow_duplicate=False), setup=luna_note,
         effects=True, **GET),
])
