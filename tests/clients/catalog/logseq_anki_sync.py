"""Catalog entries first sent by logseq-anki-sync (https://github.com/debanjandhar12/logseq-anki-sync at 0d881e3):
its requests that no other entry covers (tests/clients/logseq_anki_sync/client.py)."""


import time

from clients.support import case, named

MODEL = "DefaultModel"  # `${graphName}Model`, spaces made underscores

FIELDS = ["uuid-type", "Logseq Block UUID", "Logseq Page Id", "Text", "Breadcrumb",
          "User Controlled Field (Front)", "User Controlled Field (Back)", "User Controlled Field (Both)",
          "Config"]

UUID = "6512a0b4-0000-4000-8000-000000000001"

FRONT = ('<script src="_logseq_anki_sync_front.js" type=\'text/javascript\' async=false defer=false></script>\n'
         '        <div id="main-content">{{cloze:Text}}</div>\n'
         '        {{#User Controlled Field (Front)}}<div class="user-controlled-field-front">'
         '{{User Controlled Field (Front)}}</div>{{/User Controlled Field (Front)}}\n'
         '        <span style="display: none" class="anki-card-front-side"></span>\n'
         '        <link rel="stylesheet" href="_logseq_anki_sync_front.css">')

BACK = FRONT.replace("front", "back").replace("Front", "Back")

TEMPLATE_FILES = ["_logseq_anki_sync.css", "_logseq_anki_sync_front.css", "_logseq_anki_sync_back.css",
                  "_logseq_anki_sync.js", "_logseq_anki_sync_front.js", "_logseq_anki_sync_back.js"]

def note_fields(text):
    return {"uuid-type": f"{UUID}-cloze", "Logseq Block UUID": UUID, "Logseq Page Id": "42", "Text": text,
            "Breadcrumb": "<a href=\"logseq://graph/Default?page=Japanese\">Japanese</a>",
            "Config": "{\"dependencyHash\":\"abc\",\"assets\":[]}"}

def make_model(col, fields=FIELDS):
    mm = col.models
    m = mm.new(MODEL)
    m["type"] = 1
    for name in fields:
        mm.add_field(m, mm.new_field(name))
    t = mm.new_template("Card")
    t["qfmt"], t["afmt"] = FRONT, BACK
    mm.add_template(m, t)
    mm.add(m)
    return mm.by_name(MODEL)

def synced(col, ctx, fields=FIELDS):
    """The model, and the seeded note turned into a synced block's note (same note and card ids)."""
    mm = col.models
    m = make_model(col, fields)
    req = mm.change_notetype_info(old_notetype_id=mm.by_name("Basic")["id"], new_notetype_id=m["id"]).input
    req.note_ids.extend([ctx["nid"]])
    req.ClearField("new_fields")
    req.new_fields.extend([{"Text": 0, "Breadcrumb": 1}.get(name, -1) for name in fields])
    req.ClearField("new_templates")
    req.new_templates.extend([0])
    mm.change_notetype_of_notes(req)
    n = col.get_note(ctx["nid"])
    for k, v in note_fields("{{c1::犬}} is dog").items():
        if k in n:
            n[k] = v
    col.update_note(n)

def synced_in_filtered_learning(col, ctx):
    """The synced note's card in learning, then pulled into a filtered deck (due becomes negative)."""
    synced(col, ctx)
    c = col.get_card(ctx["cid"])
    c.type, c.queue, c.due, c.left = 1, 1, int(time.time()) + 600, 1001
    col.update_card(c)
    f = col.sched.get_or_create_filtered_deck(deck_id=0)
    f.name = "Filtered Deck 1"
    f.config.search_terms[0].search = "deck:Default"
    col.sched.add_or_update_filtered_deck(f)

def template_file(col, ctx):
    col.media.write_data("_logseq_anki_sync.css", b"s")

WHOLE = ("",)  # the envelope's two keys, and the result as used


ENTRIES = named("logseq-anki-sync", [
    # setupAnkiModel: permission, then upsertModel.
    case("createModel", "createModel", {
        "modelName": MODEL, "inOrderFields": FIELDS, "css": "", "isCloze": True,
        "cardTemplates": [{"Name": "Card", "Front": FRONT, "Back": BACK}]}, reads=["error"]),
    case("multi retrieveMediaFile template files", "multi", {"actions": [
        {"action": "retrieveMediaFile", "params": {"filename": name}} for name in TEMPLATE_FILES]},
        reads=WHOLE, setup=template_file),
    case("multi no actions", "multi", {"actions": []}, reads=WHOLE),
    case("getDecks", "getDecks", lambda c: {"cards": [c["cid"]]}, reads=WHOLE, setup=synced),
    case("getDecks learning card in a filtered deck", "getDecks", lambda c: {"cards": [c["cid"]]},
         reads=WHOLE, setup=synced_in_filtered_learning),
    case("getDecks no notes", "getDecks", {"cards": []}, reads=WHOLE),
    # AddNoteOperation: createDeck + addNote with a placeholder cloze, find it, then the real fields.
    case("multi createDeck addNote", "multi", {"actions": [
        {"action": "createDeck", "params": {"deck": "Japanese"}},
        {"action": "addNote", "params": {"note": {
            "modelName": MODEL, "deckName": "Japanese",
            "fields": {**note_fields("<b>犬</b>"), "Text": "{{c1:: placeholder}}"},
            "tags": ["Japanese"], "options": {"allowDuplicate": True}}}}]},
        reads=WHOLE, effects=True, setup=lambda col, c: make_model(col)),
    case("multi findNotes uuid-type", "multi", {"actions": [
        {"action": "findNotes", "params": {"query": f"uuid-type:{UUID}-cloze"}},
        {"action": "findNotes", "params": {"query": "uuid-type:00000000-0000-0000-0000-000000000000-cloze"}}]},
        reads=WHOLE, setup=synced),
    case("multi updateNoteFields after add", "multi", lambda c: {"actions": [
        {"action": "updateNoteFields", "params": {"note": {
            "deckName": "Default", "modelName": MODEL, "fields": note_fields("{{c1::猫}} is cat"),
            "id": c["nid"]}}}]}, reads=WHOLE, effects=True, setup=synced),
    # UpdateNoteOperation: deck, tags one at a time, then fields.
    case("multi update a note", "multi", lambda c: {"actions": [
        {"action": "changeDeck", "params": {"cards": [c["cid"]], "deck": "Japanese::Animals"}},
        {"action": "removeTags", "params": {"notes": [c["nid"]], "tags": "seeded"}},
        {"action": "addTags", "params": {"notes": [c["nid"]], "tags": "Japanese"}},
        {"action": "updateNoteFields", "params": {"note": {
            "id": c["nid"], "deckName": "Japanese::Animals", "modelName": MODEL,
            "fields": note_fields("{{c1::猫}} is cat")}}}]}, reads=WHOLE, effects=True, setup=synced),
    case("multi deleteNotes", "multi", lambda c: {"actions": [
        {"action": "deleteNotes", "params": {"notes": [c["nid"]]}}]}, reads=WHOLE, effects=True, setup=synced),
    case("reloadCollection", "reloadCollection", {}, reads=WHOLE),
])
