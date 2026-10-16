"""Catalog entries first sent by LUTE (https://github.com/LuteOrg/lute-v3 at 933d084):
its requests that no other entry covers (tests/clients/lute/client.py)."""


from clients.support import PNG, case, named, note, raw, serve

EVERYTHING = ("",)

def userimages(col, ctx):
    """ctx["lute"]: the Lute server's base URL; it serves one term image, for this case."""
    return {"lute": serve(ctx, lambda path: (200, PNG) if path == "/userimages/1/cat.jpeg" else (404, b""))}

def export_post(*actions):
    """service.py _build_ankiconnect_post_json: a multi with no version, its actions unversioned."""
    return {"action": "multi", "params": {"actions": list(actions)}}

def add(**over):
    """The note: the export's deck and note type, mapped fields, tags "lute" and the term's."""
    return {"action": "addNote", "params": {"note": note(tags=["lute", "animal"], **over)}}


ENTRIES = named("LUTE", [
    # get_anki_specs, second multi: each note type's fields (lute-anki.js L59-71).
    case("multi modelFieldNames, unversioned actions", "multi", {"actions": [
        {"action": "modelFieldNames", "params": {"modelName": name}} for name in ["Basic", "Cloze"]]},
        reads=EVERYTHING),
    # An export with { image }: the term image by URL as LUTE_TERM_<id>.jpg, then the note.
    raw("export post, term image and note", lambda c: export_post(
        {"action": "storeMediaFile", "params": {"filename": "LUTE_TERM_7.jpg",
                                                "url": c["lute"] + "/userimages/1/cat.jpeg"}},
        add(fields={"Front": "猫", "Back": '<img src="LUTE_TERM_7.jpg">'})),
        effects=True, setup=userimages),
    # The note alone, a duplicate: its inner answer is an object with error.
    raw("export post, duplicate note", lambda c: export_post(add())),
])
