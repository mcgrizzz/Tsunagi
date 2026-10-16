"""asbplayer: subtitle player (web app and extension) mining sentence cards, with an Anki word cache."""
from clients.support import B64, case, note

CLIENT = {
    "name": "asbplayer",
    "repo": "https://github.com/asbplayer/asbplayer",
    "commit": "62c4d6e",
    "read": "2026-10-15",
    "files": [
        "common/anki/anki.ts",
        "common/dictionary-db/dictionary-db-anki.ts",
        "common/annotations/anki-annotations.ts",
        "common/components/AnkiSettingsTab.tsx",
        "common/components/CardSelectView.tsx",
        "common/components/WordField.tsx",
        "common/src/fetcher.ts",
        "extension/src/handlers/video/http-post-handler.ts",
    ],
    "uses": "Anki._executeAction (anki.ts L865-889): version 6, key only if set, params left out when null; "
            "one POST per action, no multi; batches one after another",
    "notes": "Any error throws; an error containing 'duplicate' is a DuplicateNoteError. "
             "The extension proxies only 19 actions (http-post-handler.ts L5-25).",
}

# Word cache and poll queries, with word and sentence fields Front and Back and no decks,
# or deck Default (dictionary-db-anki.ts L413-427, anki.ts L370-372).
FIELDS = '"Front:_*" OR "Back:_*"'
IN_DECK = f'("deck:Default") ({FIELDS})'
# A mature cutoff of 21 (settings-provider.ts L104), so the graduated cutoff is 11.
STATUS = [
    ("is:new", f"is:new ({FIELDS})"),
    ("is:learn", f"is:learn ({FIELDS})"),
    ("prop:s>=0 (FSRS check)", f"prop:s>=0 ({FIELDS})"),
    ("prop:s graduated", f"-is:new -is:learn prop:s<11 ({FIELDS})"),
    ("prop:s young", f"-is:new -is:learn prop:s>=11 prop:s<21 ({FIELDS})"),
    ("prop:s mature", f"-is:new -is:learn prop:s>=21 ({FIELDS})"),
    ("prop:ivl graduated", f"-is:new -is:learn prop:ivl<11 ({FIELDS})"),
    ("prop:ivl young", f"-is:new -is:learn prop:ivl>=11 prop:ivl<21 ({FIELDS})"),
    ("prop:ivl mature", f"-is:new -is:learn prop:ivl>=21 ({FIELDS})"),
    ("in a deck", f"is:new ({IN_DECK})"),
]


def _review(col, c):
    """The seeded card as a review card with a 3-day interval."""
    col.sched.set_due_date([c["cid"]], "3!")


def _ten_cards(col, c):
    """Nine more cards, so cardsInfo gets a full batch of 10."""
    more = []
    for i in range(9):
        n = col.new_note(col.models.by_name("Basic"))
        n["Front"], n["Back"] = f"語{i}", f"word {i}"
        col.add_note(n, 1)
        more.append(col.card_ids_of_note(n.id)[0])
    c["more_cids"] = more


def _taken(col, c):
    """A different file already has the name asbplayer asks for."""
    col.media.write_data("asbp_Show_ep01_83400_Ab3dE6gh.jpeg", b"other")


OPTIONS = {"allowDuplicate": True, "duplicateScope": "deck",
           "duplicateScopeOptions": {"deckName": "Default", "checkChildren": False}}
AUDIO = {"filename": "asbp_Show_ep01_83400.mp3", "data": B64, "fields": ["Back"]}
PICTURE = {"filename": "asbp_Show_ep01_83400.jpeg", "data": B64, "fields": ["Back"]}


# The standard requests this client sends (tests/clients/catalog.py), run once in standard/.
ENVELOPE = {"version": 6, "params": "omit-when-empty", "key": "absent", "method": "POST"}
USES = [
    "deckNames",
    "findNotes field value",
    "findNotes newest (added:1)",
    "modelFieldNames",
    "modelNames",
    "notesInfo",
    "notesModTime",
    "requestPermission",
    "version",
]

CASES = [
    # Connection (AnkiSettingsTab.tsx L199-226): the app asks permission, the extension sends version;
    # requiresApiKey reads requireApikey, requireApiKey and the error text (anki.ts L491-497).
    # The setup tutorial's default deck and note type (AnkiSettingsTab.tsx L35-79, L359-389).
    case("createDeck Sentences", "createDeck", {"deck": "Sentences"}, reads=["error"], effects=True),
    case("createModel Sentence Card", "createModel", {
        "modelName": "Sentence Card",
        "inOrderFields": ["Sentence", "Word", "Definition", "Image", "Audio", "Source", "URL"],
        "css": ".card {\n  font-family: arial;\n  font-size: 20px;\n  text-align: center;\n  color: white;\n"
               "  background-color: black;\n}\n\n.image {\n  width: auto;\n  height: auto;\n"
               "  max-width: 500px;\n  max-height: 500px;\n  margin-left: auto;\n  margin-right: auto;\n}\n\n"
               ".front {\n  font-size: 30px;\n}",
        "cardTemplates": [{"Front": '<div class="front">{{Sentence}}</div>',
                           "Back": '<div class="front">{{Sentence}}</div>\n<hr id=answer>\n{{Definition}}\n'
                                   '<p/>\n<div class="image">\n{{Image}}\n</div>\n<p/>\n{{Audio}}\n<p/>\n'
                                   '{{Source}}\n<p/>\n{{URL}}'}],
    }, reads=["error"]),
    # Export (anki.ts L538-612): duplicates allowed, deck scope; audio and picture inline.
    case("addNote audio and picture", "addNote", {"note": {
        **note(fields={"Front": "犬が走る", "Back": "Show ep01 (00:01:23.4)"}, tags=["asbplayer"]),
        "options": OPTIONS, "audio": AUDIO, "picture": PICTURE}}, effects=True),
    case("addNote duplicate of the seeded note, no tags", "addNote", {"note": {
        **note(fields={"Front": "犬", "Back": "dog"}, tags=[]), "options": OPTIONS}}, effects=True),
    case("addNote missing deck", "addNote", {"note": {
        **note(deckName="Mining", tags=[]), "options": OPTIONS}}),
    # webm, gui and update exports store media first and use the returned name (anki.ts L702-746).
    case("storeMediaFile", "storeMediaFile",
         {"filename": "asbp_Show_ep01_83400_Ab3dE6gh.jpeg", "data": B64, "deleteExisting": False}, effects=True),
    case("storeMediaFile name taken", "storeMediaFile",
         {"filename": "asbp_Show_ep01_83400_Ab3dE6gh.jpeg", "data": B64, "deleteExisting": False},
         setup=_taken, effects=True),
    # Update last card (anki.ts L559-596, L802-821): the newest of today's notes.
    case("findNotes added:2 (same subtitle)", "findNotes", {"query": "added:2"}),
    case("updateNoteFields whole note", "updateNoteFields", lambda c: {"note": {
        **note(fields={"Front": "犬が<b>走る</b>", "Back": '<img src="asbp_Show_ep01_83400_Ab3dE6gh.jpeg">'},
               tags=["asbplayer"]),
        "options": OPTIONS, "id": c["nid"]}}, effects=True),
    case("updateNoteFields media fields only (same subtitle)", "updateNoteFields", lambda c: {"note": {
        "id": c["nid"], "fields": {"Back": "[sound:asbp_Show_ep01_83400_Ab3dE6gh.mp3]"}}}, effects=True),
    case("addTags", "addTags", lambda c: {"notes": [c["nid"]], "tags": "asbplayer mined"}, effects=True),
    # Card picker (CardSelectView.tsx L65, L111-115) and the word field's duplicate check (WordField.tsx L57).
    case("findNotes added:30", "findNotes", {"query": "added:30"}),
    case("findNotes word escaped", "findNotes", {"query": '"Front:a\\_b\\*c\\:d"'}),
    case("findNotes fields containing word", "findNotes", {"query": '"Front:*犬*" OR "Back:*犬*"'}),
    # Word cache build (dictionary-db-anki.ts L413-516).
    case("findNotes word cache", "findNotes", {"query": FIELDS}),
    case("findNotes word cache in a deck", "findNotes", {"query": IN_DECK}),
    case("cardsModTime", "cardsModTime", lambda c: {"cards": [c["cid"]]}, reads=["result[*].cardId", "error"]),
    case("cardsInfo batch of 10", "cardsInfo", lambda c: {"cards": [c["cid"], *c.get("more_cids", [])]},
         setup=_ten_cards,
         reads=["result[*].cardId", "result[*].deckName", "result[*].modelName", "result[*].due", "error"]),
    case("areSuspended", "areSuspended", lambda c: {"cards": [c["cid"]]}),
    case("areSuspended suspended", "areSuspended", lambda c: {"cards": [c["cid"]]},
         setup=lambda col, c: col.sched.suspend_cards([c["cid"]])),
    *[case(f"findCards status {name}", "findCards", {"query": q}) for name, q in STATUS],
    *[case(f"findCards status {name} (review card)", "findCards", {"query": q}, setup=_review)
      for name, q in STATUS[:9]],
    # The 10-second poll and the statistics' due cards (anki-annotations.ts L186, L241; anki.ts L362-390).
    case("findCards poll", "findCards", {"query": f"(edited:1 OR rated:1) ({FIELDS})"}),
    case("findCards poll in a deck", "findCards", {"query": f"(edited:1 OR rated:1) ({IN_DECK})"}),
    *[case(f"findCards due<={d}", "findCards", {"query": f"prop:due<={d} ({FIELDS})"}, setup=_review)
      for d in (0, 1, 7)],
]
