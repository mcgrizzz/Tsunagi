"""
Wire-shape tests for the AnkiConnect note and media actions, and the
duplicate-detection matrix that Yomitan's "already added" badge depends on.
"""
import base64

import pytest

from tsunagi.http.compat.errors import (
    DECK_NOT_FOUND,
    MODEL_NOT_FOUND,
    NOTE_DUPLICATE,
    NOTE_EMPTY,
    NOTE_NOT_FOUND,
    NOTES_INFO_NO_INPUT,
    OPTION_ALLOW_DUPLICATE_BOOL,
    OPTION_CHECK_ALL_MODELS_BOOL,
    OPTION_CHECK_CHILDREN_BOOL,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"img"
B64 = base64.b64encode(PNG).decode()


def rpc(client, action, params=None, version=6):
    body = {"action": action, "version": version}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


def note_spec(front="犬", back="dog", deck="Default", model="Basic", **extra):
    spec = {"deckName": deck, "modelName": model,
            "fields": {"Front": front, "Back": back}}
    spec.update(extra)
    return spec


class TestAddNote:
    def test_add_returns_id(self, client):
        resp = rpc(client, "addNote", {"note": note_spec()})
        assert resp["error"] is None
        assert isinstance(resp["result"], int)

    def test_bare_result_without_version(self, client):
        # Yomitan sends version 2
        body = client.post("/", json={"action": "addNote",
                                      "params": {"note": note_spec()}}).json()
        assert isinstance(body, int)

    def test_fields_are_case_insensitive(self, client):
        # createNote matches field names case-insensitively
        resp = rpc(client, "addNote", {"note": {
            "deckName": "Default", "modelName": "Basic",
            "fields": {"front": "犬", "BACK": "dog"}}})
        nid = resp["result"]
        info = rpc(client, "notesInfo", {"notes": [nid]})["result"][0]
        assert info["fields"]["Front"]["value"] == "犬"
        assert info["fields"]["Back"]["value"] == "dog"

    def test_unknown_field_is_dropped_not_an_error(self, client):
        resp = rpc(client, "addNote", {"note": note_spec(**{"fields": {
            "Front": "犬", "Nonexistent": "x"}})})
        assert resp["error"] is None

    def test_unknown_model(self, client):
        resp = rpc(client, "addNote", {"note": note_spec(model="Nope")})
        assert resp["error"] == MODEL_NOT_FOUND.format("Nope")

    def test_unknown_deck(self, client):
        resp = rpc(client, "addNote", {"note": note_spec(deck="Nope")})
        assert resp["error"] == DECK_NOT_FOUND.format("Nope")

    def test_tags_round_trip(self, client):
        nid = rpc(client, "addNote", {"note": note_spec(tags=["vocab", "jp"])})["result"]
        info = rpc(client, "notesInfo", {"notes": [nid]})["result"][0]
        assert info["tags"] == ["vocab", "jp"]


class TestAddNotes:
    def test_all_valid(self, client):
        resp = rpc(client, "addNotes", {"notes": [note_spec("犬"), note_spec("猫")]})
        assert len(resp["result"]) == 2

    def test_rollback_on_any_failure(self, client):
        # Current canonical is all-or-nothing (the stale GitHub mirror
        # returned [id, None] instead - this pins the new behavior).
        resp = rpc(client, "addNotes", {"notes": [note_spec("鳥"), note_spec(model="Nope")]})
        assert resp["result"] is None
        assert MODEL_NOT_FOUND.format("Nope") in resp["error"]
        assert rpc(client, "findNotes", {"query": "鳥"})["result"] == []


class TestCanAddNotes:
    def test_new_note_can_be_added(self, client):
        assert rpc(client, "canAddNotes", {"notes": [note_spec()]})["result"] == [True]

    def test_duplicate_cannot(self, client):
        rpc(client, "addNote", {"note": note_spec()})
        assert rpc(client, "canAddNotes", {"notes": [note_spec()]})["result"] == [False]

    def test_error_detail_success_has_no_error_key(self, client):
        (res,) = rpc(client, "canAddNotesWithErrorDetail", {"notes": [note_spec()]})["result"]
        assert res == {"canAdd": True}

    def test_error_detail_duplicate_string_is_exact(self, client):
        # Yomitan substring-matches this to show "already added"
        rpc(client, "addNote", {"note": note_spec()})
        (res,) = rpc(client, "canAddNotesWithErrorDetail", {"notes": [note_spec()]})["result"]
        assert res == {"canAdd": False, "error": NOTE_DUPLICATE}

    def test_empty_first_field(self, client):
        (res,) = rpc(client, "canAddNotesWithErrorDetail",
                     {"notes": [note_spec(front="")]})["result"]
        assert res["error"] == NOTE_EMPTY

    def test_result_length_always_matches_input(self, client):
        notes = [note_spec(), note_spec(model="Nope"), note_spec(front="")]
        assert len(rpc(client, "canAddNotes", {"notes": notes})["result"]) == 3

    def test_check_writes_nothing(self, client, fake_col):
        before = len(fake_col._notes)
        rpc(client, "canAddNotes", {"notes": [note_spec()]})
        assert len(fake_col._notes) == before


class TestDuplicateScope:
    """
    AnkiConnect's two-branch algorithm. The manual branch (scope=deck or
    checkAllModels) has deliberately different semantics from the default
    one, and clients depend on both.
    """

    @pytest.fixture()
    def scoped(self, client):
        rpc(client, "createDeck", {"deck": "JP::Verbs"})
        rpc(client, "createDeck", {"deck": "Other"})
        # Existing note lives in the child deck
        rpc(client, "addNote", {"note": note_spec(deck="JP::Verbs")})
        return client

    def can_add(self, client, **kw):
        return rpc(client, "canAddNotes", {"notes": [note_spec(**kw)]})["result"][0]

    def test_default_scope_is_collection_wide(self, scoped):
        assert self.can_add(scoped, deck="Other") is False

    def test_deck_scope_matches_in_same_deck(self, scoped):
        assert self.can_add(scoped, deck="JP::Verbs",
                            options={"duplicateScope": "deck"}) is False

    def test_deck_scope_ignores_other_decks(self, scoped):
        assert self.can_add(scoped, deck="Other",
                            options={"duplicateScope": "deck"}) is True

    def test_check_children(self, scoped):
        opts = {"duplicateScope": "deck", "duplicateScopeOptions": {"checkChildren": True}}
        assert self.can_add(scoped, deck="JP", options=opts) is False
        opts_no_children = {"duplicateScope": "deck"}
        assert self.can_add(scoped, deck="JP", options=opts_no_children) is True

    def test_scope_deck_name_overrides_note_deck(self, scoped):
        opts = {"duplicateScope": "deck",
                "duplicateScopeOptions": {"deckName": "JP::Verbs"}}
        assert self.can_add(scoped, deck="Other", options=opts) is False

    def test_invalid_scope_deck_is_not_a_duplicate(self, scoped):
        opts = {"duplicateScope": "deck", "duplicateScopeOptions": {"deckName": "NoSuchDeck"}}
        assert self.can_add(scoped, deck="JP::Verbs", options=opts) is True

    def test_html_only_field_is_empty_in_default_branch(self, client):
        (res,) = rpc(client, "canAddNotesWithErrorDetail",
                     {"notes": [note_spec(front="<br>")]})["result"]
        assert res["error"] == NOTE_EMPTY

    def test_html_only_field_is_not_empty_in_manual_branch(self, client):
        # The manual branch uses raw .strip() with no HTML stripping
        opts = {"duplicateScope": "deck", "duplicateScopeOptions": {"checkAllModels": True}}
        assert self.can_add(client, front="<br>", options=opts) is True

    def test_check_all_models_crosses_notetypes(self, client):
        rpc(client, "createDeck", {"deck": "X"})
        rpc(client, "addNote", {"note": {"deckName": "X", "modelName": "Cloze",
                                         "fields": {"Text": "{{c1::犬}}"}}})
        same = {"duplicateScope": "deck", "duplicateScopeOptions": {"checkAllModels": True}}
        assert self.can_add(client, front="{{c1::犬}}", deck="X", options=same) is False
        diff = {"duplicateScope": "deck", "duplicateScopeOptions": {"checkAllModels": False}}
        assert self.can_add(client, front="{{c1::犬}}", deck="X", options=diff) is True

    @pytest.mark.parametrize("options,message", [
        ({"allowDuplicate": 1}, OPTION_ALLOW_DUPLICATE_BOOL),
        ({"duplicateScopeOptions": {"checkChildren": "yes"}}, OPTION_CHECK_CHILDREN_BOOL),
        ({"duplicateScopeOptions": {"checkAllModels": 0}}, OPTION_CHECK_ALL_MODELS_BOOL),
    ])
    def test_non_bool_options_rejected(self, client, options, message):
        (res,) = rpc(client, "canAddNotesWithErrorDetail",
                     {"notes": [note_spec(options=options)]})["result"]
        assert res["error"] == message

    def test_allow_duplicate_permits(self, client):
        rpc(client, "addNote", {"note": note_spec()})
        resp = rpc(client, "addNote", {"note": note_spec(options={"allowDuplicate": True})})
        assert resp["error"] is None


class TestUpdateNoteFields:
    def test_updates_named_fields_only(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        rpc(client, "updateNoteFields", {"note": {"id": nid, "fields": {"Back": "hound"}}})
        info = rpc(client, "notesInfo", {"notes": [nid]})["result"][0]
        assert info["fields"]["Front"]["value"] == "犬"
        assert info["fields"]["Back"]["value"] == "hound"

    def test_is_exact_case_unlike_add(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        rpc(client, "updateNoteFields", {"note": {"id": nid, "fields": {"back": "nope"}}})
        info = rpc(client, "notesInfo", {"notes": [nid]})["result"][0]
        assert info["fields"]["Back"]["value"] == "dog"  # unchanged

    def test_returns_null(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        resp = rpc(client, "updateNoteFields", {"note": {"id": nid, "fields": {"Back": "x"}}})
        assert resp == {"result": None, "error": None}

    def test_missing_note(self, client):
        resp = rpc(client, "updateNoteFields", {"note": {"id": 999999, "fields": {"Back": "x"}}})
        assert resp["error"] == NOTE_NOT_FOUND.format(999999)

    def test_attaches_audio_to_existing_note(self, client, fake_col):
        # asbplayer's "update last card with audio" flow
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        resp = rpc(client, "updateNoteFields", {"note": {
            "id": nid, "fields": {"Back": "dog"},
            "audio": {"filename": "word.mp3", "data": B64, "fields": ["Back"]}}})
        assert resp == {"result": None, "error": None}
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert info["fields"]["Back"]["value"] == "dog[sound:word.mp3]"
        assert fake_col.media.have("word.mp3")

    def test_attaches_picture_to_existing_note(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        rpc(client, "updateNoteFields", {"note": {
            "id": nid, "fields": {},
            "picture": {"filename": "pic.png", "data": B64, "fields": ["Back"]}}})
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert info["fields"]["Back"]["value"].endswith('<img src="pic.png">')


class TestNotesInfo:
    def test_exact_key_set(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert set(info) == {"noteId", "profile", "tags", "fields", "modelName", "mod", "cards"}

    def test_fields_are_a_map_with_order(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert info["fields"] == {"Front": {"value": "犬", "order": 0},
                                  "Back": {"value": "dog", "order": 1}}

    def test_missing_note_is_empty_dict(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        result = rpc(client, "notesInfo", {"notes": [nid, 999999]})["result"]
        assert result[1] == {}          # not null - Yomitan relies on this
        assert result[0]["noteId"] == nid

    def test_query_form(self, client):
        rpc(client, "addNote", {"note": note_spec()})
        assert len(rpc(client, "notesInfo", {"query": "犬"})["result"]) == 1

    def test_requires_notes_or_query(self, client):
        assert rpc(client, "notesInfo", {})["error"] == NOTES_INFO_NO_INPUT

    def test_cards_are_ints(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert info["cards"] and all(isinstance(c, int) for c in info["cards"])


class TestFindAndDeleteNotes:
    def test_find_without_query_is_empty(self, client):
        assert rpc(client, "findNotes", {})["result"] == []

    def test_find_returns_ints(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        assert rpc(client, "findNotes", {"query": "犬"})["result"] == [nid]

    def test_delete(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        assert rpc(client, "deleteNotes", {"notes": [nid]}) == {"result": None, "error": None}
        assert rpc(client, "findNotes", {"query": "犬"})["result"] == []


class TestTags:
    """asbplayer calls addTags right after updateNoteFields when tags are set."""

    def test_add_tags(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        assert rpc(client, "addTags", {"notes": [nid], "tags": "mined asbplayer"}) == \
            {"result": None, "error": None}
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert info["tags"] == ["mined", "asbplayer"]

    def test_add_tags_is_idempotent(self, client):
        nid = rpc(client, "addNote", {"note": note_spec(tags=["mined"])})["result"]
        rpc(client, "addTags", {"notes": [nid], "tags": "mined"})
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert info["tags"] == ["mined"]

    def test_remove_tags(self, client):
        nid = rpc(client, "addNote", {"note": note_spec(tags=["a", "b"])})["result"]
        rpc(client, "removeTags", {"notes": [nid], "tags": "a"})
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert info["tags"] == ["b"]

    def test_get_tags(self, client):
        rpc(client, "addNote", {"note": note_spec(front="犬", tags=["vocab"])})
        rpc(client, "addNote", {"note": note_spec(front="猫", tags=["verb"])})
        assert rpc(client, "getTags", {})["result"] == ["verb", "vocab"]

    def test_notes_mod_time(self, client):
        nid = rpc(client, "addNote", {"note": note_spec()})["result"]
        (entry,) = rpc(client, "notesModTime", {"notes": [nid]})["result"]
        assert entry["noteId"] == nid
        assert isinstance(entry["mod"], int)


class TestNoteMedia:
    def test_picture_appends_img_markup(self, client):
        nid = rpc(client, "addNote", {"note": note_spec(picture={
            "filename": "dog.png", "data": B64, "fields": ["Back"]})})["result"]
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert info["fields"]["Back"]["value"].endswith('<img src="dog.png">')
        assert info["fields"]["Back"]["value"].startswith("dog")  # appended, not replaced

    def test_audio_and_video_use_sound_markup(self, client):
        nid = rpc(client, "addNote", {"note": note_spec(
            audio={"filename": "a.mp3", "data": B64, "fields": ["Back"]},
            video={"filename": "v.mp4", "data": B64, "fields": ["Back"]})})["result"]
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        value = info["fields"]["Back"]["value"]
        assert "[sound:a.mp3]" in value and "[sound:v.mp4]" in value

    def test_list_form_and_null_entries(self, client):
        resp = rpc(client, "addNote", {"note": note_spec(picture=[
            {"filename": "a.png", "data": B64, "fields": ["Back"]}, None])})
        assert resp["error"] is None

    def test_fields_optional_stores_without_markup(self, client, fake_col):
        nid = rpc(client, "addNote", {"note": note_spec(picture={
            "filename": "solo.png", "data": B64})})["result"]
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert "<img" not in info["fields"]["Back"]["value"]
        assert fake_col.media.have("solo.png")

    def test_unknown_target_field_is_skipped(self, client):
        resp = rpc(client, "addNote", {"note": note_spec(picture={
            "filename": "a.png", "data": B64, "fields": ["Nonexistent"]})})
        assert resp["error"] is None

    def test_markup_uses_stored_name_after_rename(self, client):
        rpc(client, "storeMediaFile", {"filename": "dup.png", "data": B64})
        other = base64.b64encode(b"totally different").decode()
        nid = rpc(client, "addNote", {"note": note_spec(picture={
            "filename": "dup.png", "data": other, "fields": ["Back"]})})["result"]
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert '<img src="dup.png">' not in info["fields"]["Back"]["value"]
        assert "<img src=" in info["fields"]["Back"]["value"]

    def test_media_failure_appends_escaped_error_and_still_creates(self, client):
        nid = rpc(client, "addNote", {"note": note_spec(picture={
            "filename": "bad.png", "data": "not base64!!", "fields": ["Back"]})})["result"]
        (info,) = rpc(client, "notesInfo", {"notes": [nid]})["result"]
        assert info["fields"]["Back"]["value"] != "dog"  # error text appended
        assert "<" not in info["fields"]["Back"]["value"].replace("&lt;", "")

    def test_media_failure_without_fields_does_not_crash(self, client):
        resp = rpc(client, "addNote", {"note": note_spec(
            front="独自", picture={"filename": "bad.png", "data": "not base64!!"})})
        assert resp["error"] is None  # canonical raises KeyError here; we guard

    def test_media_is_attached_before_duplicate_check(self, client):
        # Adding media to the FIRST field changes the dedup outcome
        rpc(client, "addNote", {"note": note_spec()})
        resp = rpc(client, "addNote", {"note": note_spec(picture={
            "filename": "x.png", "data": B64, "fields": ["Front"]})})
        assert resp["error"] is None


class TestMediaActions:
    def test_store_and_retrieve_round_trip(self, client):
        assert rpc(client, "storeMediaFile",
                   {"filename": "a.png", "data": B64})["result"] == "a.png"
        got = rpc(client, "retrieveMediaFile", {"filename": "a.png"})["result"]
        assert base64.b64decode(got) == PNG

    def test_store_requires_a_source(self, client):
        resp = rpc(client, "storeMediaFile", {"filename": "a.png"})
        assert "data" in resp["error"] and "url" in resp["error"]

    def test_skip_hash_match_returns_null_and_writes_nothing(self, client, fake_col):
        import hashlib
        digest = hashlib.md5(PNG).hexdigest()
        resp = rpc(client, "storeMediaFile",
                   {"filename": "a.png", "data": B64, "skipHash": digest})
        assert resp == {"result": None, "error": None}
        assert not fake_col.media.have("a.png")

    def test_skip_hash_mismatch_stores(self, client):
        resp = rpc(client, "storeMediaFile",
                   {"filename": "a.png", "data": B64, "skipHash": "0" * 32})
        assert resp["result"] == "a.png"

    def test_delete_existing_false_renames_on_collision(self, client):
        rpc(client, "storeMediaFile", {"filename": "a.png", "data": B64})
        other = base64.b64encode(b"different").decode()
        resp = rpc(client, "storeMediaFile",
                   {"filename": "a.png", "data": other, "deleteExisting": False})
        assert resp["result"] != "a.png"

    def test_retrieve_missing_is_false(self, client):
        assert rpc(client, "retrieveMediaFile", {"filename": "nope.png"})["result"] is False

    def test_retrieve_strips_path_traversal(self, client):
        assert rpc(client, "retrieveMediaFile",
                   {"filename": "../../secret.txt"})["result"] is False

    def test_get_media_files_names(self, client):
        rpc(client, "storeMediaFile", {"filename": "a.png", "data": B64})
        rpc(client, "storeMediaFile", {"filename": "b.mp3", "data": B64})
        assert rpc(client, "getMediaFilesNames", {})["result"] == ["a.png", "b.mp3"]
        assert rpc(client, "getMediaFilesNames", {"pattern": "*.mp3"})["result"] == ["b.mp3"]

    def test_delete_media_file(self, client, fake_col):
        rpc(client, "storeMediaFile", {"filename": "a.png", "data": B64})
        assert rpc(client, "deleteMediaFile", {"filename": "a.png"}) == {"result": None, "error": None}
        assert not fake_col.media.have("a.png")
