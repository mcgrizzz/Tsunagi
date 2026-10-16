"""Catalog entries first sent by anki-editor (https://github.com/anki-editor/anki-editor at defeab6):
its requests that no other entry covers (tests/clients/anki_editor/client.py)."""


from clients.catalog.standard import second_note
from clients.support import case, named

MULTI_READS = ["result[*].result", "result[*].error", "error"]


def req(action, **params):
    """A queued request (anki-editor-api-enqueue-request): version 6, params when given."""
    return {"action": action, "version": 6, "params": params}


def org_note(front, back, nid=0, deck="Default", tags=("org",), allow=False):
    """anki-editor-api--note: id 0 for a new note, allowDuplicate always sent, tags a list."""
    return {"id": nid, "deckName": deck, "modelName": "Basic", "fields": {"Front": front, "Back": back},
            "options": {"allowDuplicate": allow}, "tags": list(tags)}


def create(note):
    """anki-editor--enqueue-create-note: createDeck, then addNote."""
    return [req("createDeck", deck=note["deckName"]), req("addNote", note=note)]


ENTRIES = named("anki-editor", [
    # A push of new headings: one round, each note's deck made first.
    case("multi push new notes", "multi", {"actions": [
        *create(org_note("猫", "cat", deck="Org")),
        *create(org_note("鳥", "")),
        *create(org_note("犬", "dog", allow=True)),
        *create(org_note("魚", "fish", tags=())),
        *create(org_note("犬", "dog")),
    ]}, reads=MULTI_READS, effects=True),
    # New and changed headings in one round: the changed one's notesInfo.
    case("multi push new and changed notes", "multi", lambda c: {"actions": [
        *create(org_note("猫", "cat")), req("notesInfo", notes=[c["nid"]])]},
        reads=MULTI_READS, effects=True),
    # The next round: updateNote with the whole Org note (its deck and options too), one missing.
    case("multi updateNote", "multi", lambda c: {"actions": [
        req("updateNote", note=org_note("犬", "dog!", nid=c["nid"])),
        req("updateNote", note=org_note("猫", "", nid=c["nid2"])),
        req("updateNote", note=org_note("犬", "dog?", nid=c["nid"], tags=("org", "marked"), allow=True)),
        req("updateNote", note=org_note("犬", "dog?", nid=c["nid"], deck="Org", tags=())),
        req("updateNote", note=org_note("蛇", "snake", nid=12345)),
    ]}, reads=MULTI_READS, setup=second_note(), effects=True),
])
