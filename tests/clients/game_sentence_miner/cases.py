"""Game Sentence Miner: watches for notes Yomitan adds and fills in audio, screenshot and sentence."""
from clients.support import B64, case

CLIENT = {
    "name": "Game Sentence Miner",
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

WHOLE = [""]
NOTE_READS = ["result[*].noteId", "result[*].modelName", "result[*].tags", "result[*].fields",
              "result[*].cards", "error"]
# anki_card_sync.py _fetch_and_upsert_notes / _fetch_and_upsert_cards. It also stores each
# note's mod, left out: a mod read on its own is a bare time, which the comparison can't mask.
CACHE_NOTE_READS = ["result[*].noteId", "result[*].modelName", "result[*].fields", "result[*].tags",
                    "error"]
CACHE_CARD_READS = ["result[*].cardId", "result[*].note", "result[*].deckName", "result[*].queue",
                    "result[*].type", "result[*].due", "result[*].interval", "result[*].factor",
                    "result[*].reps", "result[*].lapses", "error"]
# Ids no note or card has: a batch of 500 holds notes deleted since the last findNotes.
GONE = list(range(1500000000001, 1500000000500))

# store_media_file sends the whole local path as the filename (anki.py:3075).
WINDOWS_AUDIO = r"C:\Users\Jo Smith\AppData\Roaming\GameSentenceMiner\temp\GameName_2026-10-15-12-00-00-123.opus"
LINUX_SHOT = "/home/jo/.config/GameSentenceMiner/temp/screenshot_2026-10-15-12-00-00-123.png"


def tagged_overlay(col, ctx):
    n = col.get_note(ctx["nid"])
    n.tags = ["seeded", "overlay"]
    col.update_note(n)


def reviewed(col, ctx):
    col.db.execute("insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type)"
                   " values (?, ?, -1, 3, 1, 0, 2500, 6000, 0)", 1760000000000, ctx["cid"])



# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "always", "key": "absent", "method": "POST"}
USES = [
    "deckNames",
    "deleteNotes",
    "findNotes newest (added:1)",
    "modelFieldNames",
    "modelNames",
    "notesInfo",
    "version",
]

CASES = [
    # Reachability (anki.py _is_anki_connect_reachable, anki_setup.py check, the stats probe).
    # The monitor loop, every polling_rate_v2 ms (anki.py get_note_ids): only result is read.
    # update_new_cards: AnkiCard.from_dict of each new note.
    # Media: the returned name goes into [sound:...] or <img src="...">. AnkiConnect's writeData
    # takes os.path.basename first, so the answer depends on the OS Anki runs on: these
    # references are Linux's, where a backslash is not a separator.
    case("storeMediaFile Windows path", "storeMediaFile", {"filename": WINDOWS_AUDIO, "data": B64},
         reads=WHOLE, effects=True),
    case("storeMediaFile Linux path", "storeMediaFile", {"filename": LINUX_SHOT, "data": B64},
         reads=WHOLE, effects=True),
    # _update_anki_note: fields, then tags.
    case("updateNoteFields", "updateNoteFields", lambda c: {"note": {"id": c["nid"], "fields": {
        "Back": "犬が<b>好き</b>だ<br>[sound:GameName_2026-10-15-12-00-00-123.opus]"}}},
         reads=WHOLE, effects=True),
    # Default field settings on a note type without them: _apply_field_policy doesn't check.
    case("updateNoteFields fields the note lacks", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {
            "Sentence": "犬が好きだ", "SentenceAudio": "[sound:GameName_2026-10-15-12-00-00-123.opus]",
            "Picture": '<img src="screenshot_2026-10-15-12-00-00-123.png">'}}},
         reads=WHOLE, effects=True),
    case("addTags", "addTags", lambda c: {"tags": "GSM Game::GameName", "notes": [c["nid"]]},
         reads=WHOLE, effects=True),
    case("removeTags overlay", "removeTags", lambda c: {"tags": "overlay", "notes": [c["nid"]]},
         setup=tagged_overlay, reads=WHOLE, effects=True),
    # _delete_cancelled_anki_note, and the duplicate after a field-grouping merge.
    # Field grouping (_find_field_grouping_candidates, _apply_field_grouping_merge).
    case("findNotes field grouping", "findNotes", {"query": 'note:"Basic" "Front:犬"'}, reads=WHOLE),
    case("updateNoteFields grouped", "updateNoteFields", lambda c: {"note": {"id": c["nid"], "fields": {
        "Back": '<span data-group-id="2">猫が好きだ</span><span data-group-id="1">dog</span>'}}},
         reads=WHOLE, effects=True),
    # Cache sync (anki_card_sync.py _build_sync_query, run_full_sync, run_incremental_sync).
    case("findNotes sync scope", "findNotes", {"query": "Front:_*"}, reads=WHOLE),
    case("findNotes sync scope with note type", "findNotes", {"query": 'Front:_* note:"Basic"'},
         reads=WHOLE),
    case("findNotes default word field", "findNotes", {"query": "Expression:_*"}, reads=WHOLE),
    case("findCards sync scope", "findCards", {"query": "Front:_*"}, reads=WHOLE),
    case("findCards incremental", "findCards",
         lambda c: {"query": f"nid:{c['nid']} OR nid:1500000000001"}, reads=WHOLE),
    case("notesInfo batch of 500", "notesInfo", lambda c: {"notes": [c["nid"], *GONE]},
         reads=CACHE_NOTE_READS),
    case("cardsInfo batch of 500", "cardsInfo", lambda c: {"cards": [c["cid"], *GONE]},
         reads=CACHE_CARD_READS),
    case("getReviewsOfCards", "getReviewsOfCards", lambda c: {"cards": [c["cid"]]},
         setup=reviewed, reads=["result", "error"]),
    # anki_setup.py setup and the settings window (config_gui_qt.py _anki_invoke).
    case("createDeck", "createDeck", {"deck": "Mining"}, reads=WHOLE, effects=True),
]
