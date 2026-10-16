"""anki-editor: an Emacs minor mode that pushes Org-mode headings to Anki as notes.

Every call goes through anki-editor.el `anki-editor-api-call`: json-encode
of {action, version: 6, params} with params left out when there are none,
POSTed by running curl --data-binary (so no Content-Type: application/json).
`anki-editor-api-call-result` raises on a non-null `error` and returns
`result`. Pushing notes queues requests and sends each round as one `multi`
(versioned sub-actions, each answer's own error and result read): createDeck
and addNote for new notes, notesInfo for changed ones; their callbacks queue
updateNote, then changeDeck, for the next rounds. Actions are elisp symbols
('addNote), so a text scan misses them.
"""

from clients.support import NOTE

CLIENT = {
    "name": "anki-editor",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Emacs mode; pushes Org-mode notes",
    "repo": "https://github.com/anki-editor/anki-editor",
    "commit": "defeab6",
    "read": "2026-10-16",
    "files": ["anki-editor.el"],
    "uses": "curl POST, no Content-Type; version 6; params left out when empty; multi sub-actions carry version 6",
    "notes": ("Turning the mode on checks version >= 6. Every note it sends (addNote, updateNote) "
              "carries id (0 for a new note), options.allowDuplicate (false unless "
              "anki-editor-allow-duplicates) and tags as a list. An update keeps the protected "
              "tags (marked, leech) it read with notesInfo and moves the note's cards with changeDeck. "
              "A failed sub-action's error is written to the heading's ANKI_FAILURE_REASON. Media: "
              "retrieveMediaFile first, storeMediaFile only when it answers false. "
              "Not tested: guiBrowse, guiAddCards, sync."),
}

ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}

# anki-editor-api--note: an Org heading's note. Empty headings make empty fields.
ORG_NOTE = {**NOTE, "id": int, "options": {"allowDuplicate": False}}
PUSH = {"action": "createDeck", "version": int}, {"action": "addNote", "version": int}
MULTI_READS = ("result[*].result", "result[*].error")


def notes(*over):
    return [{"note": {**ORG_NOTE, **o}} for o in over]


# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addNote": (
        notes({}, {"fields": {str: (str, "")}}, {"options": {"allowDuplicate": True}}, {"tags": []}),
        (),
    ),
    "changeDeck": ([{"cards": [int], "deck": str}], ()),
    "createDeck": ([{"deck": str}], ()),
    "deckNames": ([{}], ("result", "error")),
    "deleteNotes": ([{"notes": [int]}], ("error",)),
    "findNotes": ([{"query": str}, {"query": ""}], ("result", "error")),
    "getTags": ([{}], ("result", "error")),
    "modelFieldNames": ([{"modelName": str}], ("result", "error")),
    "modelNames": ([{}], ("result", "error")),
    "modelStyling": ([{"modelName": str}], ("result.css", "error")),
    "multi": (
        [
            # anki-editor--with-collection-data-updated: every note type's fields (error checked).
            {"actions": [{"action": "modelFieldNames", "version": int}]},
            # Push rounds (anki-editor-api-dispatch-queue): the outer error isn't read.
            {"actions": list(PUSH)},
            {"actions": [{"action": "notesInfo", "version": int}]},
            {"actions": [*PUSH, {"action": "notesInfo", "version": int}]},
            {"actions": [{"action": "updateNote", "version": int}]},
            {"actions": [{"action": "changeDeck", "version": int}]},
        ],
        (*MULTI_READS, "error"),
    ),
    "notesInfo": ([{"notes": [int]}], ()),
    "retrieveMediaFile": ([{"filename": str}], ("result", "error")),
    "storeMediaFile": ([{"data": str, "filename": str}], ("error",)),
    "updateModelStyling": ([{"model": {"css": str, "name": str}}], ("error",)),
    "updateNote": (
        notes({}, {"fields": {str: (str, "")}}, {"options": {"allowDuplicate": True}}, {"tags": []}),
        (),
    ),
    "version": ([{}], ("result", "error")),
}
