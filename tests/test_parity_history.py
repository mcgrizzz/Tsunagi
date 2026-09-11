"""Behavioral regressions selected from SourceHut history through de6e6e1b."""

import base64
from pathlib import Path

import pytest

from tsunagi.http.compat.actions import gui


def rpc(client, action, **params):
    response = client.post("/", json={"action": action, "version": 6, "params": params})
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def history_note(col):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "history audit"
    note.tags = ["audit_keep", "audit_remove"]
    col.add_note(note, 1)
    return note


def test_deprecated_select_note_keeps_note_parameter(client, monkeypatch):
    # ab4d964 renamed the new action, but the old alias still accepts `note`.
    selected = []
    monkeypatch.setattr(gui.g, "ac_select_card", lambda cid: selected.append(cid) or True)
    assert rpc(client, "guiSelectNote", note=123) == {"result": True, "error": None}
    assert rpc(client, "guiSelectCard", card=456) == {"result": True, "error": None}
    assert selected == [123, 456]


def test_add_tags_undocumented_remove_switch(client, col, history_note):
    assert rpc(client, "addTags", notes=[history_note.id], tags="audit_remove", add=False) == {
        "result": None, "error": None,
    }
    assert col.get_note(history_note.id).tags == ["audit_keep"]
    assert rpc(client, "addTags", notes=[history_note.id], tags="audit_added")["error"] is None
    assert set(col.get_note(history_note.id).tags) == {"audit_keep", "audit_added"}


def test_suspend_undocumented_reverse_switch(client, col, history_note):
    cid = col.card_ids_of_note(history_note.id)[0]
    assert rpc(client, "suspend", cards=[cid])["result"] is True
    assert rpc(client, "suspend", cards=[cid], suspend=False)["result"] is True
    assert col.get_card(cid).queue != -1


def test_notes_info_query_precedence_and_large_id_list(client, col, history_note):
    # e5e6d25 introduced query; 6ae3d59/cf4c902/fcd67b2 batched ID lookups.
    queried = rpc(client, "notesInfo", notes=[-1], query=f"nid:{history_note.id}")
    assert queried["error"] is None
    row = queried["result"][0]
    assert row["noteId"] == history_note.id
    assert row["mod"] == col.get_note(history_note.id).mod
    assert row["cards"] == col.card_ids_of_note(history_note.id)
    requested = [history_note.id] * 1001 + [-1]
    listed = rpc(client, "notesInfo", notes=requested)
    assert listed["error"] is None
    # Upstream's SQL batches each append the note's cards once.
    batched_row = dict(row, cards=row["cards"] * 2)
    assert listed["result"] == [batched_row] * 1001 + [{}]


def test_add_notes_rolls_back_successes_on_later_error(client, col):
    # f52e0c2 changed addNotes from per-note nulls to error + rollback.
    before = set(col.find_notes(""))
    common = {"deckName": "Default", "fields": {"Front": "history rollback"}}
    result = rpc(client, "addNotes", notes=[
        {**common, "modelName": "Basic"},
        {**common, "modelName": "missing history model"},
    ])
    assert result["result"] is None
    assert result["error"] is not None
    assert set(col.find_notes("")) == before


def test_note_media_without_target_fields(client, col):
    # b4f26b1 + 068b7ec allow storing media without appending it to fields.
    result = rpc(client, "addNote", note={
        "deckName": "Default", "modelName": "Basic",
        "fields": {"Front": "history media"},
        "audio": {"filename": "history-media.mp3", "data": base64.b64encode(b"audit").decode()},
    })
    assert result["error"] is None
    assert col.get_note(result["result"])["Front"] == "history media"
    assert (Path(col.media.dir()) / "history-media.mp3").read_bytes() == b"audit"


@pytest.mark.parametrize("payload", [
    {"action": {}, "version": 6},
    {"action": [], "version": 6},
    {"action": "multi", "version": 6, "params": ["invalid"]},
    {"action": "multi", "version": 6, "params": {"actions": [
        {"action": {}, "version": 6}, {"action": "version", "version": 6},
    ]}},
])
def test_malformed_rpc_stays_in_protocol_envelope(client, payload):
    response = client.post("/", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"result", "error"}
    if isinstance(body["result"], list):
        assert body["result"][0]["error"] == "unsupported action"
        assert body["result"][1] == {"result": 6, "error": None}
    else:
        assert body["result"] is None and isinstance(body["error"], str)
