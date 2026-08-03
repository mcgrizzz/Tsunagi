"""
Wire-shape golden tests for the AnkiConnect note-update and tag actions,
quoted from canonical (git.sr.ht/~foosoft/anki-connect).
"""
import pytest

from tsunagi.http.compat import actions  # noqa: F401  (registers the handlers)
from tsunagi.http.compat.errors import (
    NOTE_NOT_FOUND,
    NOTE_UPDATE_NO_INPUT,
    TAGS_MUST_BE_LIST,
)

MISSING = 999999


def rpc(client, action, params=None, version=6):
    body = {"action": action, "version": version}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


def add(client, front="犬", back="dog", tags=None, model="Basic"):
    note = {"deckName": "Default", "modelName": model,
            "fields": {"Front": front, "Back": back}, "tags": tags or []}
    if model == "Cloze":
        note["fields"] = {"Text": front, "Back Extra": back}
    return rpc(client, "addNote", {"note": note})["result"]


def info(client, nid):
    return rpc(client, "notesInfo", {"notes": [nid]})["result"][0]


class TestCanAddSingular:
    def test_can_add(self, client):
        result = rpc(client, "canAddNote", {"note": {
            "deckName": "Default", "modelName": "Basic",
            "fields": {"Front": "新しい"}}})["result"]
        assert result is True

    def test_cannot_add_duplicate(self, client):
        add(client, "犬")
        result = rpc(client, "canAddNote", {"note": {
            "deckName": "Default", "modelName": "Basic",
            "fields": {"Front": "犬"}}})["result"]
        assert result is False

    def test_error_detail_success_has_no_error_key(self, client):
        result = rpc(client, "canAddNoteWithErrorDetail", {"note": {
            "deckName": "Default", "modelName": "Basic",
            "fields": {"Front": "新しい"}}})["result"]
        assert result == {"canAdd": True}

    def test_error_detail_failure_carries_the_reason(self, client):
        add(client, "犬")
        result = rpc(client, "canAddNoteWithErrorDetail", {"note": {
            "deckName": "Default", "modelName": "Basic",
            "fields": {"Front": "犬"}}})["result"]
        assert result["canAdd"] is False
        # Yomitan's "already added" badge substring-matches this.
        assert "duplicate" in result["error"]


class TestUpdateNote:
    def test_fields_only(self, client):
        nid = add(client, tags=["keep"])
        assert rpc(client, "updateNote", {"note": {
            "id": nid, "fields": {"Back": "hound"}}}) == {"result": None, "error": None}
        note = info(client, nid)
        assert note["fields"]["Back"]["value"] == "hound"
        assert note["tags"] == ["keep"]

    def test_tags_only(self, client):
        nid = add(client, tags=["old"])
        rpc(client, "updateNote", {"note": {"id": nid, "tags": ["new"]}})
        assert info(client, nid)["tags"] == ["new"]

    def test_both(self, client):
        nid = add(client, tags=["old"])
        rpc(client, "updateNote", {"note": {
            "id": nid, "fields": {"Back": "hound"}, "tags": ["new"]}})
        note = info(client, nid)
        assert note["fields"]["Back"]["value"] == "hound" and note["tags"] == ["new"]

    def test_neither_is_an_error(self, client):
        nid = add(client)
        assert rpc(client, "updateNote", {"note": {"id": nid}})["error"] == \
            NOTE_UPDATE_NO_INPUT

    def test_empty_tag_list_still_counts_as_supplied(self, client):
        nid = add(client, tags=["old"])
        resp = rpc(client, "updateNote", {"note": {"id": nid, "tags": []}})
        assert resp["error"] is None
        assert info(client, nid)["tags"] == []


class TestUpdateNoteModel:
    def test_converts_the_note(self, client):
        nid = add(client, tags=["keep"])
        resp = rpc(client, "updateNoteModel", {"note": {
            "id": nid, "modelName": "Cloze",
            "fields": {"Text": "{{c1::犬}}"}, "tags": ["converted"]}})
        assert resp == {"result": None, "error": None}
        note = info(client, nid)
        assert note["modelName"] == "Cloze"
        assert note["fields"]["Text"]["value"] == "{{c1::犬}}"
        assert note["tags"] == ["converted"]

    def test_unknown_model_is_an_error(self, client):
        nid = add(client)
        resp = rpc(client, "updateNoteModel", {"note": {
            "id": nid, "modelName": "Nope", "fields": {"Front": "x"}}})
        assert "Nope" in resp["error"]


class TestNoteTags:
    def test_get_note_tags(self, client):
        nid = add(client, tags=["a", "b"])
        assert rpc(client, "getNoteTags", {"note": nid})["result"] == ["a", "b"]

    def test_get_note_tags_missing_note(self, client):
        assert rpc(client, "getNoteTags",
                   {"note": MISSING})["error"] == NOTE_NOT_FOUND.format(MISSING)

    def test_update_note_tags_replaces(self, client):
        nid = add(client, tags=["a", "b"])
        assert rpc(client, "updateNoteTags",
                   {"note": nid, "tags": ["c"]}) == {"result": None, "error": None}
        assert info(client, nid)["tags"] == ["c"]

    def test_update_note_tags_accepts_a_bare_string(self, client):
        nid = add(client, tags=["a"])
        rpc(client, "updateNoteTags", {"note": nid, "tags": "solo"})
        assert info(client, nid)["tags"] == ["solo"]

    def test_update_note_tags_rejects_other_types(self, client):
        nid = add(client)
        for bad in (5, [1, 2], {"a": 1}):
            assert rpc(client, "updateNoteTags",
                       {"note": nid, "tags": bad})["error"] == TAGS_MUST_BE_LIST

    def test_clear_unused_tags_returns_null(self, client):
        add(client, tags=["a"])
        assert rpc(client, "clearUnusedTags") == {"result": None, "error": None}


class TestReplaceTags:
    @pytest.fixture()
    def seeded(self, client):
        self.a = add(client, "犬", tags=["verb", "verb::transitive"])
        self.b = add(client, "猫", tags=["noun"])
        return client

    def test_replaces_the_exact_tag_only(self, seeded):
        # Not col.tags.rename: children keep their own name.
        assert rpc(seeded, "replaceTags", {
            "notes": [self.a], "tag_to_replace": "verb",
            "replace_with_tag": "action"}) == {"result": None, "error": None}
        assert info(seeded, self.a)["tags"] == ["verb::transitive", "action"]

    def test_leaves_other_notes_alone(self, seeded):
        rpc(seeded, "replaceTags", {"notes": [self.a], "tag_to_replace": "noun",
                                    "replace_with_tag": "x"})
        assert info(seeded, self.b)["tags"] == ["noun"]

    def test_missing_notes_are_skipped(self, seeded):
        resp = rpc(seeded, "replaceTags", {
            "notes": [self.a, MISSING], "tag_to_replace": "verb",
            "replace_with_tag": "action"})
        assert resp["error"] is None

    def test_replace_in_all_notes(self, seeded):
        rpc(seeded, "replaceTagsInAllNotes", {"tag_to_replace": "noun",
                                              "replace_with_tag": "thing"})
        assert info(seeded, self.b)["tags"] == ["thing"]
        assert info(seeded, self.a)["tags"] == ["verb", "verb::transitive"]


class TestRemoveEmptyNotes:
    def test_removes_note_types_nothing_uses(self, client):
        # Canonical's behaviour despite the name: "empty note" reads as
        # "empty note type". Destroys no content - use_count 0 means no notes.
        add(client, "犬")                      # Basic is now in use
        before = rpc(client, "modelNames")["result"]
        assert set(before) == {"Basic", "Cloze"}

        assert rpc(client, "removeEmptyNotes") == {"result": None, "error": None}
        assert rpc(client, "modelNames")["result"] == ["Basic"]

    def test_keeps_notes(self, client):
        nid = add(client, "犬")
        rpc(client, "removeEmptyNotes")
        assert info(client, nid)["noteId"] == nid
