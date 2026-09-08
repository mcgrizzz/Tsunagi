"""Permission state regressions that run without an upstream checkout or Qt."""

import copy

import pytest

from tsunagi.adapters.config import DEFAULTS, _migrate
from tsunagi.adapters.dialogs import PermissionDecision
from tsunagi.adapters.settings import Settings
from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc


@pytest.mark.parametrize("origin", ["", "https://permission.test"])
@pytest.mark.parametrize("decision", [
    PermissionDecision(accepted=True), PermissionDecision(), PermissionDecision(ignore=True),
])
def test_http_permission_decision_persists_and_controls_next_request(
    client, reset_settings, monkeypatch, origin, decision,
):
    writes, prompts = [], []
    reset_settings.configure({**copy.deepcopy(DEFAULTS), "api_key": "retained-key"},
                             persist=lambda cfg: writes.append(copy.deepcopy(cfg)))

    def ask(value):
        prompts.append(value)
        return decision

    monkeypatch.setattr("tsunagi.http.compat.ankiconnect._default_ask", ask)
    for _ in range(2):
        response = client.post("/", json={"action": "requestPermission", "version": 6},
                               headers={"Origin": origin})
        assert response.status_code == 200
        assert response.json()["result"]["permission"] == ("granted" if decision else "denied")
    persists = bool(decision or (origin and decision.ignore))
    assert len(writes) == (1 if persists else 0)
    assert prompts == [origin] * (1 if persists else 2)
    if writes:
        assert writes[0]["api_key"] == "retained-key"
        migrated, _ = _migrate(copy.deepcopy(writes[0]))
        restored = Settings(migrated)
        if decision:
            assert restored.is_origin_allowed(origin)
        else:
            assert restored.get("ankiconnect_ignore_origins") == [origin]
            assert not restored.is_origin_allowed(origin)


@pytest.mark.parametrize("origin", [None, "", 0, False, [], {}])
def test_falsy_nested_origins_are_not_added_to_ignore_list(origin):
    writes, prompts = [], []
    settings = Settings(copy.deepcopy(DEFAULTS), persist=writes.append)

    def ask(value):
        prompts.append(value)
        return PermissionDecision(ignore=True)

    request = {"action": "multi", "version": 6, "params": {"actions": [
        {"action": "requestPermission", "version": 6, "params": {"origin": origin, "allowed": False}},
    ]}}
    for _ in range(2):
        response = handle_ankiconnect_rpc(request, settings=settings, ask_permission=ask)
        assert response["result"] == [{"result": {"permission": "denied"}, "error": None}]
    assert prompts == [origin, origin]
    assert writes == []


def test_nested_acceptance_keeps_duplicate_writes_in_shim():
    writes = []
    settings = Settings(copy.deepcopy(DEFAULTS), persist=lambda cfg: writes.append(copy.deepcopy(cfg)))
    response = handle_ankiconnect_rpc({
        "action": "multi", "version": 6, "params": {"actions": [
            {"action": "requestPermission", "version": 6,
             "params": {"origin": "http://localhost", "allowed": False}},
        ] * 2},
    }, settings=settings, ask_permission=lambda origin: True)
    assert all(child["result"]["permission"] == "granted" for child in response["result"])
    assert [len(cfg["cors_allowlist"]) for cfg in writes] == [2, 3]
    # Native settings retain their existing deduplication contract.
    settings.add_cors_origin("http://localhost")
    assert len(writes) == 2
