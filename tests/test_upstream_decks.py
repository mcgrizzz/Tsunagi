"""AnkiConnect deck configuration and preset-operation differential tests.

Requires TSUNAGI_ANKICONNECT_CHECKOUT; see upstream_support for shared fixtures.
Keep new deck/preset cases here rather than growing the general comparison suite.
"""

import copy

import pytest
from upstream_support import compare, first_difference
from upstream_support import pair as pair
from upstream_support import upstream as upstream

from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc


def deck_config_state(collection):
    """Persisted preset values and deck assignments, excluding write timestamps."""
    configs = {
        config["id"]: {key: value for key, value in config.items() if key not in {"mod", "usn"}}
        for config in collection.decks.all_config()
    }
    decks = {
        deck.name: collection.decks.get(deck.id)
        for deck in collection.decks.all_names_and_ids()
    }
    decks = {name: {key: value for key, value in deck.items() if key not in {"mod", "usn"}}
             for name, deck in decks.items()}
    return configs, decks


@pytest.mark.parametrize("name", [None, False, True, 0, 1.5, [], {}, "", "missing", "Default", "default", " Default ", "Parity::日本語"])
def test_deck_config_raw_names(pair, name):
    compare(pair, "getDeckConfig", {"deck": name})
    assert deck_config_state(pair[0]) == deck_config_state(pair[1])


@pytest.mark.parametrize("config", [None, False, True, 0, 1.5, "", "config", [], {}, [1], {"id": 1}, {"id": "1"}])
def test_deck_config_raw_objects(pair, config):
    compare(pair, "saveDeckConfig", {"config": config})
    assert deck_config_state(pair[0]) == deck_config_state(pair[1])


@pytest.mark.parametrize("field,value", [
    ("name", None), ("name", False), ("name", 123), ("name", []),
    ("id", None), ("id", False), ("id", "1"), ("id", -1),
    ("new", None), ("new", []), ("new", {}),
    ("rev", None), ("rev", {}), ("lapse", {}),
    ("maxTaken", "30"), ("maxTaken", -1), ("autoplay", None),
    ("new.perDay", 7), ("new.perDay", "7"), ("new.perDay", -1),
    ("new.delays", [1, 10]), ("new.delays", []), ("new.delays", "1 10"),
    ("new.order", 0), ("new.order", 1), ("new.order", 3),
    ("rev.perDay", 42), ("rev.ivlFct", 0.8), ("rev.ivlFct", "0.8"),
    ("lapse.leechAction", 1), ("unknownOption", {"nested": True}),
    ("mod", None), ("mod", "bad"), ("usn", None), ("usn", []),
])
def test_deck_config_nested_values(pair, field, value):
    config = copy.deepcopy(pair[0].decks.get_config(1))
    if "." in field:
        group, key = field.split(".")
        config[group][key] = value
    else:
        config[field] = value
    compare(pair, "saveDeckConfig", {"config": config})
    assert deck_config_state(pair[0]) == deck_config_state(pair[1])


@pytest.mark.parametrize("filtered", [False, True])
def test_deck_config_read_complete_fields(pair, filtered):
    name = "Parity::日本語"
    if filtered:
        for col in pair[:2]:
            col.decks.new_filtered("Config filtered")
        name = "Config filtered"
    request = {"action": "getDeckConfig", "version": 6, "params": {"deck": name}}
    actual = handle_ankiconnect_rpc(copy.deepcopy(request))
    expected = pair[2].handler(copy.deepcopy(request))
    if filtered:
        for reply, col in zip((actual, expected), pair[:2]):
            if isinstance(reply["result"], dict):
                assert reply["result"]["id"] == col.decks.by_name(name)["id"]
                reply["result"].pop("id")
                reply["result"].pop("mod")
    assert actual == expected, first_difference(actual, expected)


@pytest.mark.parametrize("value", [True, 0, 1.0, 1.5, "", "1.0", " 1 ", [], {}, "missing", 9999999999999, 2**63])
def test_deck_config_id_validation(pair, value):
    config = copy.deepcopy(pair[0].decks.get_config(1))
    config["id"] = value
    compare(pair, "saveDeckConfig", {"config": config})
    assert deck_config_state(pair[0]) == deck_config_state(pair[1])


@pytest.mark.parametrize("key", ["id", "name", "mod", "usn", "maxTaken", "autoplay", "new", "rev", "lapse"])
def test_deck_config_missing_members(pair, key):
    config = copy.deepcopy(pair[0].decks.get_config(1))
    del config[key]
    compare(pair, "saveDeckConfig", {"config": config})
    assert deck_config_state(pair[0]) == deck_config_state(pair[1])


@pytest.mark.parametrize("order", [0, 1])
def test_deck_config_save_scheduling_and_undo(pair, order):
    config = copy.deepcopy(pair[0].decks.get_config(1))
    config["new"]["order"] = order
    config["new"]["perDay"] = 7
    result = compare(pair, "saveDeckConfig", {"config": config})
    assert result == {"result": True, "error": None}
    assert deck_config_state(pair[0]) == deck_config_state(pair[1])
    assert pair[0].db.all("select id, due, queue from cards order by id") == pair[1].db.all(
        "select id, due, queue from cards order by id")
    statuses = [col.undo_status() for col in pair[:2]]
    assert statuses[0].undo == statuses[1].undo
    if statuses[0].undo:
        for col in pair[:2]:
            col.undo()
        assert deck_config_state(pair[0]) == deck_config_state(pair[1])
        for col in pair[:2]:
            col.redo()
        assert deck_config_state(pair[0]) == deck_config_state(pair[1])


def test_deck_config_save_publishes_changes(pair):
    from tsunagi.adapters.anki.compat import save_deck_config_legacy

    config = copy.deepcopy(pair[0].decks.get_config(1))
    config["new"]["perDay"] = 7
    result = save_deck_config_legacy.__wrapped__(pair[0], config)
    assert result.changes.deck_config
    assert pair[0].decks.get_config(1)["new"]["perDay"] == 7


def preset_operation_state(col, created_id=None):
    configs, decks = deck_config_state(col)
    if created_id is not None:
        created = configs.pop(created_id)
        created["id"] = "created"
        configs["created"] = created
    for name, deck in decks.items():
        deck["id"] = name
        if created_id is not None and deck.get("conf") == created_id:
            deck["conf"] = "created"
    return configs, decks, col.db.all("select id, due, queue, ivl from cards order by id")


def compare_preset_operation(pair, action, params):
    request = {"action": action, "version": 6, "params": params}
    expected = pair[2].handler(copy.deepcopy(request))
    actual = handle_ankiconnect_rpc(copy.deepcopy(request))
    states = []
    for reply, col in zip((actual, expected), pair[:2]):
        created_id = None
        if action == "cloneDeckConfigId" and type(reply["result"]) is int:
            created_id = reply["result"]
            assert created_id in {config["id"] for config in col.decks.all_config()}
            reply["result"] = "created"
        states.append(preset_operation_state(col, created_id))
    assert actual == expected, first_difference(actual, expected)
    assert states[0] == states[1], first_difference(list(states[0]), list(states[1]))
    return actual


def seed_custom_preset(pair):
    for col in pair[:2]:
        config = copy.deepcopy(col.decks.get_config(1))
        config.update(id=424242, name="Custom preset")
        config["new"]["perDay"] = 7
        config["rev"]["perDay"] = 42
        col.decks.update_config(config)
        assert config["id"] == 424242
        for name in ("Parity", "Parity::日本語"):
            deck = col.decks.by_name(name)
            deck["conf"] = config["id"]
            col.decks.save(deck)


_PRESET_IDS = [None, False, True, 0, 1, 1.5, "1", "1.5", "", " 1 ", [], {}, -1,
               9999999999999, 2**63, 424242, "424242", 424242.5]


@pytest.mark.parametrize("action,parameter", [
    ("setDeckConfigId", "configId"), ("cloneDeckConfigId", "cloneFrom"),
    ("removeDeckConfigId", "configId"),
])
@pytest.mark.parametrize("value", _PRESET_IDS)
def test_preset_operation_raw_ids(pair, action, parameter, value):
    seed_custom_preset(pair)
    params = {parameter: value}
    if action == "setDeckConfigId":
        params["decks"] = ["Parity", "Parity::日本語"]
    elif action == "cloneDeckConfigId":
        params["name"] = "Copied preset"
    compare_preset_operation(pair, action, params)


@pytest.mark.parametrize("decks", [None, False, 1, "", "Default", [], {},
    {"Parity": True}, [None], [[]], [{}], ["missing"], ["default"],
    ["Parity", "Parity"], ["Parity", "missing"], ["missing", "Parity"],
    ["Parity", []], ["Parity", "Parity::日本語"],
])
@pytest.mark.parametrize("config_id", [1, "bad"])
def test_preset_assignment_raw_decks_and_precedence(pair, decks, config_id):
    seed_custom_preset(pair)
    compare_preset_operation(pair, "setDeckConfigId", {"decks": decks, "configId": config_id})


@pytest.mark.parametrize("name", [None, False, True, 0, 1.5, [], {}, "", "Default", "日本語", "Custom preset"])
@pytest.mark.parametrize("source", [1, 9999999999999, "bad"])
def test_preset_clone_name_and_source_precedence(pair, name, source):
    seed_custom_preset(pair)
    compare_preset_operation(pair, "cloneDeckConfigId", {"name": name, "cloneFrom": source})


def test_preset_clone_default_source(pair):
    compare_preset_operation(pair, "cloneDeckConfigId", {"name": "Default source"})


@pytest.mark.parametrize("action,params", [
    ("setDeckConfigId", {"decks": ["Parity", "Parity::日本語"], "configId": 1}),
    ("removeDeckConfigId", {"configId": 424242}),
])
def test_preset_operation_undo_redo(pair, action, params):
    seed_custom_preset(pair)
    compare_preset_operation(pair, action, params)
    statuses = [col.undo_status() for col in pair[:2]]
    assert statuses[0].undo == statuses[1].undo
    if statuses[0].undo:
        for col in pair[:2]:
            col.undo()
        assert preset_operation_state(pair[0]) == preset_operation_state(pair[1])
        for col in pair[:2]:
            col.redo()
        assert preset_operation_state(pair[0]) == preset_operation_state(pair[1])


@pytest.mark.parametrize("config_id", [1, 424242, "bad", 2**63])
def test_preset_assignment_filtered_decks(pair, config_id):
    seed_custom_preset(pair)
    actual_id, reference_id = [col.decks.new_filtered("Filtered preset test") for col in pair[:2]]
    # Upstream also reads aqt.mw.col directly; both collections need matching IDs.
    pair[1].db.execute("update decks set id=? where id=?", actual_id, reference_id)
    compare_preset_operation(pair, "setDeckConfigId", {
        "decks": ["Parity", "Filtered preset test", "Parity::日本語"], "configId": config_id,
    })


@pytest.mark.parametrize("failure_index", [0, 1, 2])
def test_preset_assignment_keeps_saved_prefix(pair, monkeypatch, failure_index):
    seed_custom_preset(pair)
    for col in pair[:2]:
        original_save = col.decks.save
        calls = []

        def save(deck, original_save=original_save, calls=calls):
            calls.append(deck["name"])
            if len(calls) - 1 == failure_index:
                raise RuntimeError("injected preset assignment failure")
            return original_save(deck)

        monkeypatch.setattr(col.decks, "save", save)
    result = compare_preset_operation(pair, "setDeckConfigId", {
        "decks": ["Parity", "Parity::日本語", "Default"], "configId": 1,
    })
    assert result == {"result": False, "error": None}
    assert pair[0].decks.by_name("Parity")["conf"] == (1 if failure_index > 0 else 424242)
    assert pair[0].decks.by_name("Parity::日本語")["conf"] == (1 if failure_index > 1 else 424242)


@pytest.mark.parametrize("config_id", [424242, "424242", 424242.0])
def test_preset_removal_failure_keeps_assignment_changes(pair, monkeypatch, config_id):
    seed_custom_preset(pair)

    def fail_remove(_):
        raise RuntimeError("injected preset removal failure")

    for col in pair[:2]:
        monkeypatch.setattr(col._backend, "remove_deck_config", fail_remove)
    result = compare_preset_operation(pair, "removeDeckConfigId", {"configId": config_id})
    assert result == {"result": None, "error": "injected preset removal failure"}
    for col in pair[:2]:
        expected = 424242 if isinstance(config_id, float) else 1
        assert col.decks.by_name("Parity")["conf"] == expected
        assert 424242 in {config["id"] for config in col.decks.all_config()}


def test_preset_partial_changes_are_published(pair, monkeypatch):
    from tsunagi.adapters.anki.compat import (
        remove_deck_config_legacy,
        set_deck_config_legacy,
    )

    seed_custom_preset(pair)
    col = pair[0]
    original_save = col.decks.save

    def fail_second(deck):
        if deck["name"] == "Parity::日本語":
            raise RuntimeError("later save failed")
        return original_save(deck)

    with monkeypatch.context() as patch:
        patch.setattr(col.decks, "save", fail_second)
        result = set_deck_config_legacy.__wrapped__(col, ["Parity", "Parity::日本語"], 1)
    assert result.changes.deck
    assert col.decks.by_name("Parity")["conf"] == 1
    assert col.decks.by_name("Parity::日本語")["conf"] == 424242

    def fail_remove(_):
        raise RuntimeError("later removal failed")

    monkeypatch.setattr(col._backend, "remove_deck_config", fail_remove)
    result = remove_deck_config_legacy.__wrapped__(col, 424242)
    assert result.changes.deck
    assert col.decks.by_name("Parity::日本語")["conf"] == 1
