"""Catalog entries first sent by Saladict (https://github.com/crimx/ext-saladict at 7d93a65):
its requests that no other entry covers (tests/clients/saladict/client.py)."""


from clients.support import case, named

DECK = "Saladict"

MODEL = "Saladict Word"

FIELDS = ["Date", "Text", "Translation", "Context", "ContextCloze", "Note", "Title", "Url",
          "Favicon", "Audio"]

DATE = "1700000000000"

def card_text(front, nf):
    """cardText() in index.ts L368-398."""
    hint = "hint:" if front else ""
    return (f"{{{{#{nf[4]}}}}}\n<section>{{{{cloze:{nf[4]}}}}}</section>\n"
            f"<section>{{{{type:cloze:{nf[4]}}}}}</section>\n"
            f"{{{{#{nf[2]}}}}}\n<section>{{{{{nf[2]}}}}}</section>\n{{{{/{nf[2]}}}}}\n"
            f"{{{{/{nf[4]}}}}}\n\n"
            f"{{{{^{nf[4]}}}}}\n<h1>{{{{{nf[1]}}}}}</h1>\n"
            f"{{{{#{nf[2]}}}}}\n<section>{{{{{nf[2]}}}}}</section>\n{{{{/{nf[2]}}}}}\n"
            f"{{{{/{nf[4]}}}}}\n\n"
            f"{{{{#{nf[5]}}}}}\n<section>{{{{{hint}{nf[5]}}}}}</section>\n{{{{/{nf[5]}}}}}\n\n"
            f"{{{{#{nf[6]}}}}}\n<section class=\"tsource\">\n<hr />\n"
            f"{{{{#{nf[8]}}}}}\n<span class=\"favicon\" style=\"background-image:url({{{{{nf[8]}}}}})\"></span>\n"
            f"{{{{/{nf[8]}}}}}\n<a href=\"{{{{{nf[7]}}}}}\">{{{{{nf[6]}}}}}</a>\n</section>\n"
            f"{{{{/{nf[6]}}}}}\n")

# cardCss() in index.ts L400-476.
CSS = (
    '.card {\n'
    '  font-family: arial;\n'
    '  font-size: 20px;\n'
    '  text-align: center;\n'
    '  color: #333;\n'
    '  background-color: white;\n'
    '}\n'
    '\n'
    'a {\n'
    '  color: #5caf9e;\n'
    '}\n'
    '\n'
    'input {\n'
    '  border: 1px solid #eee;\n'
    '}\n'
    '\n'
    'section {\n'
    '  margin: 1em 0;\n'
    '}\n'
    '\n'
    '.trans {\n'
    '  border: 1px solid #eee;\n'
    '  padding: 0.5em;\n'
    '}\n'
    '\n'
    '.trans_title {\n'
    '  display: block;\n'
    '  font-size: 0.9em;\n'
    '  font-weight: bold;\n'
    '}\n'
    '\n'
    '.trans_content {\n'
    '  margin-bottom: 0.5em;\n'
    '}\n'
    '\n'
    '.cloze {\n'
    '  font-weight: bold;\n'
    '  color: #f9690e;\n'
    '}\n'
    '\n'
    '.tsource {\n'
    '  position: relative;\n'
    '  font-size: .8em;\n'
    '}\n'
    '\n'
    '.tsource img {\n'
    '  height: .7em;\n'
    '}\n'
    '\n'
    '.tsource a {\n'
    '  text-decoration: none;\n'
    '}\n'
    '\n'
    '.typeGood {\n'
    '  color: #fff;\n'
    '  background: #1EBC61;\n'
    '}\n'
    '\n'
    '.typeBad {\n'
    '  color: #fff;\n'
    '  background: #F75C4C;\n'
    '}\n'
    '\n'
    '.typeMissed {\n'
    '  color: #fff;\n'
    '  background: #7C8A99;\n'
    '}\n'
    '\n'
    '.favicon {\n'
    '  display: inline-block;\n'
    '  width: 1em;\n'
    '  height: 1em;\n'
    '  background: center/cover no-repeat;\n'
    '}\n')

# wordToFields() for a word saved from a page (index.ts L235-271), escaping on.
WORD = {"Date": DATE, "Text": "dog", "Translation": "犬", "Context": "a dog barks",
        "ContextCloze": "a {{c1::dog}} barks", "Note": "", "Title": "Example",
        "Url": "https://example.com/", "Favicon": "", "Audio": ""}

def with_model(col, ctx):
    """The deck and note type as Saladict's createDeck and createModel leave them."""
    col.decks.id(DECK)
    mm = col.models
    m = mm.new(MODEL)
    for name in FIELDS:
        mm.add_field(m, mm.new_field(name))
    t = mm.new_template("Saladict Cloze")
    t["qfmt"], t["afmt"] = card_text(True, FIELDS), card_text(False, FIELDS)
    mm.add_template(m, t)
    mm.add(m)

def with_word(col, ctx):
    """with_model, and the word already in Anki; its note id replaces ctx's nid."""
    with_model(col, ctx)
    n = col.new_note(col.models.by_name(MODEL))
    for name, value in WORD.items():
        n[name] = value
    col.add_note(n, col.decks.id(DECK))
    ctx["nid"] = n.id

def scase(name, action, params=None, **kw):
    """The envelope's key: null, and params {} when there are none."""
    p = params if params is not None else {}
    return case(name, action, p, key=None, **kw)

ADD = {"note": {"deckName": DECK, "modelName": MODEL,
                "options": {"allowDuplicate": False, "duplicateScope": "deck"},
                "tags": [], "fields": WORD}}


ENTRIES = named("Saladict", [
    scase("createModel", "createModel",
          {"modelName": MODEL, "inOrderFields": FIELDS, "css": CSS,
           "cardTemplates": [{"Name": "Saladict Cloze", "Front": card_text(True, FIELDS),
                              "Back": card_text(False, FIELDS)}]},
          reads=["error"]),
    scase("addNote", "addNote", ADD, setup=with_model, effects=True),
    # Word editor "update Anki": the found note id with all the fields.
    scase("updateNoteFields", "updateNoteFields",
          lambda c: {"note": {"id": c["nid"], "fields": {**WORD, "Note": "barks a lot"}}},
          setup=with_word, effects=True),
])
