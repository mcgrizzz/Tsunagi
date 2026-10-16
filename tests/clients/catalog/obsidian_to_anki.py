"""Catalog entries first sent by Obsidian_to_Anki (https://github.com/ObsidianToAnki/Obsidian_to_Anki at feb3db2):
its requests that no other entry covers (tests/clients/obsidian_to_anki/client.py)."""


from clients.support import B64, named, raw

TAG = "Obsidian_to_Anki"

def req(action, **params):
    """anki.ts request() / obsidian_to_anki.py AnkiConnect.request(): params always present."""
    return {"action": action, "version": 6, "params": params}

def multi(*actions):
    return req("multi", actions=list(actions))

def new_note(front, back, tags, **extra):
    """setting-to-data.ts template, filled by note.ts parse() and file.ts scanNotes()."""
    return {"deckName": "Default", "modelName": "Basic",
            "fields": {"Front": front, "Back": back},
            "options": {"allowDuplicate": False, "duplicateScope": "deck"},
            "tags": tags, **extra}

def plugin_requests_1(files, media):
    """files-manager.ts requests_1: per file (createDecks, addNotes, noteIds, updates, deletes)."""
    return req("multi", actions=[
        multi(*[multi(*[req("createDeck", deck=n["deckName"]) for n in f["add"]]) for f in files]),
        multi(*[multi(*[req("addNote", note=n) for n in f["add"]]) for f in files]),
        multi(*[req("notesInfo", notes=[i for i, _ in f["edit"]]) for f in files]),
        req("getTags"),
        multi(*[multi(*[req("updateNoteFields", note={"id": i, "fields": flds}) for i, flds in f["edit"]])
                for f in files]),
        multi(*[req("deleteNotes", notes=f["delete"]) for f in files]),
        multi(*media),
    ])

def file(add=(), edit=(), delete=()):
    return {"add": list(add), "edit": list(edit), "delete": list(delete)}


ENTRIES = named("Obsidian_to_Anki", [
    # Startup (main.ts getDefaultSettings/generateFieldsDict) and every scan (scanVault).
    # setting-to-data.ts L28: every note id in the collection.
    # First scan of two files: one new note without FILE TAGS (tags [TAG, ""], the request
    # AnkiConnect's 2026-10-11 rewrite broke) and one image by path; the other file has no notes,
    # so every one of its entries is empty. Index 5 after slice(1) is the media multi.
    raw("requests_1 new note with empty tag, media by path, empty file", lambda c: plugin_requests_1(
        [file(add=[new_note("<p>猫</p>", "<p>cat</p>", [TAG, ""])]), file()],
        [req("storeMediaFile", filename="local.png", path=c["png_path"])]), effects=True),
    # Rescan: a duplicate new note (an error inside the third level, which parse() logs), and an
    # edit of an existing note (notesInfo for its cards, then updateNoteFields).
    raw("requests_1 duplicate add and an edit", lambda c: plugin_requests_1(
        [file(add=[new_note("犬", "<p>dog</p>", [TAG, ""])],
              edit=[(c["nid"], {"Front": "<p>犬</p>", "Back": "<p>dog!</p>"})]),
         file()], []), effects=True),
    # A DELETE line, notes with FILE TAGS (no empty tag), a target deck not yet in Anki.
    raw("requests_1 delete line and file tags", lambda c: plugin_requests_1(
        [file(delete=[c["nid"]]),
         file(add=[{**new_note("<p>猫</p>", "<p>cat</p>", [TAG, "jp", "animals"]), "deckName": "Obsidian::JP"}])],
        []), effects=True),
    # files-manager.ts requests_2: changeDeck per file (cards from notesInfo, [] when no edits),
    # removeTags of every tag in the collection only for files with edits, addTags per edit
    # (note tags + " " + FILE TAGS, so a trailing space when there are none).
    raw("requests_2 move, replace tags", lambda c: req("multi", actions=[
        multi(req("changeDeck", cards=[c["cid"]], deck="Obsidian"), req("changeDeck", cards=[], deck="Default")),
        multi(req("removeTags", notes=[c["nid"]], tags="seeded")),
        multi(multi(req("addTags", notes=[c["nid"]], tags=TAG + " ")), multi()),
    ]), effects=True),
    # obsidian_to_anki.py get_fields: modelFieldNames of every model in one multi.
    raw("script get_fields", lambda c: multi(req("modelFieldNames", modelName="Basic"),
                                            req("modelFieldNames", modelName="Cloze"))),
    # obsidian_to_anki.py main: getTags, media as base64, then per directory a multi of
    # (addNotes, notesInfo, updateFields, deleteNotes), each per file: four levels.
    # Notes carry "audio": [] and updateNoteFields sends it too.
    raw("script requests_1", lambda c: multi(
        req("getTags"),
        multi(req("storeMediaFile", filename="image.png", data=B64)),
        multi(
            multi(multi(req("addNote", note=new_note("<p>猫</p>", "<p>cat</p>", [TAG, ""], audio=[]))),
                  multi()),
            multi(req("notesInfo", notes=[c["nid"]]), req("notesInfo", notes=[])),
            multi(multi(req("updateNoteFields", note={"id": c["nid"], "fields": {"Front": "<p>犬</p>",
                                                                                "Back": "<p>dog!</p>"},
                                                      "audio": []})),
                  multi()),
            multi(req("deleteNotes", notes=[]), req("deleteNotes", notes=[])),
        )), effects=True),
    # obsidian_to_anki.py requests_2: removeTags is sent for every file, even with no notes.
    raw("script requests_2", lambda c: multi(multi(
        multi(req("changeDeck", cards=[c["cid"]], deck="Default"), req("changeDeck", cards=[], deck="Default")),
        multi(req("removeTags", notes=[c["nid"]], tags="seeded"), req("removeTags", notes=[], tags="seeded")),
        multi(multi(req("addTags", notes=[c["nid"]], tags=TAG + " ")), multi()),
    )), effects=True),
])
