"""HTTP and multi request boundaries, without an upstream checkout dependency."""

import pytest


def test_null_params_are_rejected_before_dispatch(client, monkeypatch):
    from tsunagi.http.compat.registry import registry

    def unexpected_dispatch(*args, **kwargs):
        pytest.fail("invalid HTTP params reached an action handler")

    monkeypatch.setattr(registry, "handle", unexpected_dispatch)
    response = client.post("/", json={"action": "version", "version": 6, "params": None})
    assert response.status_code == 200
    assert response.json() == {"result": None, "error": (
        "None is not of type 'object'\n\n"
        "Failed validating 'type' in schema['properties']['params']:\n"
        "    {'type': 'object'}\n\nOn instance['params']:\n    None")}


@pytest.mark.parametrize("malformed", [None, "invalid", []])
def test_multi_stops_after_malformed_entry_without_rolling_back(col, client, malformed):
    response = client.post("/", json={
        "action": "multi", "version": 6, "params": {"actions": [
            {"action": "createDeck", "params": {"deck": "Shape prefix"}},
            malformed,
            {"action": "createDeck", "params": {"deck": "Shape suffix"}},
        ]},
    })
    assert response.status_code == 200
    assert response.json() == {"result": None, "error": (
        f"'{type(malformed).__name__}' object has no attribute 'get'")}
    assert col.decks.by_name("Shape prefix") is not None
    assert col.decks.by_name("Shape suffix") is None


@pytest.mark.parametrize("actions", [[], {}, ""])
def test_multi_accepts_empty_iterables(client, actions):
    response = client.post("/", json={
        "action": "multi", "version": 6, "params": {"actions": actions},
    })
    assert response.json() == {"result": [], "error": None}
