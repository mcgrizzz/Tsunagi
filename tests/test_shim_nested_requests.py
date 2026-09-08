"""Nested request regressions independent of the optional upstream checkout."""

import pytest

from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc


def test_nested_null_parameters_keep_the_next_sibling(client):
    reply = client.post("/", json={
        "action": "multi", "version": 6, "params": {"actions": [
            {"action": "version", "version": 6, "params": None},
            {"action": "version", "version": 6},
        ]},
    }).json()
    assert reply == {"result": [
        {"result": None, "error": (
            "AnkiConnect.version() argument after ** must be a mapping, not NoneType")},
        {"result": 6, "error": None},
    ], "error": None}


@pytest.mark.parametrize("version", [None, "6", {}, []])
def test_nested_bad_version_does_not_undo_completed_write(col, client, version):
    reply = client.post("/", json={
        "action": "multi", "version": 6, "params": {"actions": [
            {"action": "createDeck", "version": version, "params": {"deck": "Version write"}},
            {"action": "version", "version": 6},
        ]},
    }).json()
    assert reply == {"result": [
        {"result": None, "error": (
            f"'<=' not supported between instances of '{type(version).__name__}' and 'int'")},
        {"result": 6, "error": None},
    ], "error": None}
    assert col.decks.by_name("Version write") is not None


def test_nested_fractional_version_keeps_the_envelope(client):
    reply = client.post("/", json={
        "action": "multi", "version": 6, "params": {"actions": [
            {"action": "version", "version": 4.5},
        ]},
    }).json()
    assert reply == {"result": [{"result": 6, "error": None}], "error": None}


def test_nested_permission_missing_context_fails_without_prompt():
    prompts = []
    reply = handle_ankiconnect_rpc({
        "action": "multi", "version": 6, "params": {"actions": [
            {"action": "requestPermission", "version": 6},
        ]},
    }, settings={}, ask_permission=lambda origin: prompts.append(origin))
    assert reply == {"result": [{"result": None, "error": (
        "AnkiConnect.requestPermission() missing 2 required positional arguments: 'origin' and 'allowed'"
    )}], "error": None}
    assert prompts == []


@pytest.mark.parametrize("allowed", [True, False, None, "yes"])
def test_nested_permission_uses_supplied_allowed_value(allowed):
    prompts = []

    def deny(origin):
        prompts.append(origin)
        return False

    reply = handle_ankiconnect_rpc({
        "action": "multi", "version": 6, "params": {"actions": [
            {"action": "requestPermission", "version": 6,
             "params": {"origin": "", "allowed": allowed}},
        ]},
    }, settings={}, ask_permission=deny)
    permission = {"permission": "granted", "requireApikey": False, "version": 6} if allowed else {
        "permission": "denied"}
    assert reply == {"result": [{"result": permission, "error": None}], "error": None}
    assert prompts == ([] if allowed else [""])
