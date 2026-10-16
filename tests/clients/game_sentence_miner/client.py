"""Game Sentence Miner: watches for notes Yomitan adds and fills in audio, screenshot and sentence."""

from clients.support import PATH

CLIENT = {
    "name": "Game Sentence Miner",
    # For docs/compatible_clients.md (tools/compatible_clients.py).
    "about": "Adds audio, screenshots and sentences to mined notes",
    "needs": ("0.7.5", "for media files named with a folder"),
    "repo": "https://github.com/bpwhelan/GameSentenceMiner",
    "commit": "c3499a0",
    "read": "2026-10-15",
    "files": [
        "GameSentenceMiner/anki.py",
        "GameSentenceMiner/anki_setup.py",
        "GameSentenceMiner/ui/config_gui_qt.py",
        "GameSentenceMiner/util/cron/anki_card_sync.py",
        "GameSentenceMiner/util/cron/anki_word_sync.py",
        "GameSentenceMiner/web/anki_api_endpoints.py",
        "GameSentenceMiner/util/platform/notification.py",
    ],
    "uses": "requests.post, version 6, params always sent ({} when none); urllib for anki_word_sync.py",
    "notes": "anki.py invoke needs exactly the two keys result and error. Field names follow the "
             "user's settings (defaults Expression, Sentence, SentenceAudio, Picture); the cases map "
             "the word to Front and the sentence to Back of the seeded Basic note. The bundled "
             "Hachidori and Yomitan extensions in GSM_Overlay are separate clients, not covered here.",
}

ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}

# Each action its code sends: (each distinct request's shape, tests/clients/support.py;
# what it reads of the answer).
SENDS = {
    "addTags": ([{"notes": [int], "tags": str}], ("",)),
    "cardsInfo": (
        [{"cards": [int]}],
        ("result[*].cardId", "result[*].note", "result[*].deckName", "result[*].queue", "result[*].type", "result[*].due", "result[*].interval", "result[*].factor", "result[*].reps", "result[*].lapses", "error"),
    ),
    "createDeck": ([{"deck": str}], ("",)),
    "deckNames": ([{}], ("",)),
    "deleteNotes": ([{"notes": [int]}], ("",)),
    "findCards": ([{"query": str}], ("",)),
    "findNotes": ([{"query": str}], ("result", "")),
    "getReviewsOfCards": ([{"cards": [int]}], ("result", "error")),
    "modelFieldNames": ([{"modelName": str}], ("",)),
    "modelNames": ([{}], ("",)),
    "notesInfo": (
        [{"notes": [int]}],
        ("result[*].noteId", "result[*].modelName", "result[*].tags", "result[*].fields", "result[*].cards", "error"),
    ),
    "removeTags": ([{"notes": [int], "tags": str}], ("",)),
    "storeMediaFile": ([{"data": str, "filename": PATH}], ("",)),
    "updateNoteFields": ([{"note": {"fields": {str: str}, "id": int}}], ("",)),
    "version": ([{}], ("",)),
}
