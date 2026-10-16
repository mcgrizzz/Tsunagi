"""Catalog entries first sent by simple-anki-sync (https://github.com/russluber/simple-anki-sync at 36ddadd):
its requests that no other entry covers (tests/clients/simple_anki_sync/client.py)."""


from clients.support import case, named

MANAGED = "obsidian_simple_anki_sync_created"


ENTRIES = named("simple-anki-sync", [
    case("updateNoteFields missing note", "updateNoteFields",
         {"note": {"id": 1234567890123, "fields": {"Front": "犬", "Back": "dog"}}}, reads=["error"]),
    # fetchNotesInfo: as many infos as ids, each with its noteId and number cards; tags for updateNote.
    case("updateNoteTags", "updateNoteTags", lambda c: {"note": c["nid"], "tags": ["seeded", MANAGED]},
         effects=True),
])
