"""Permission replies, prompt choices and config writes against pinned upstream."""

import copy
import json
import os
import sys
from types import SimpleNamespace

import pytest

from tools.upstream_reference import load_reference
from tsunagi.adapters.settings import Settings
from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc


@pytest.fixture(scope="module")
def reference():
    checkout = os.environ.get("TSUNAGI_ANKICONNECT_CHECKOUT")
    if not checkout:
        pytest.skip("Set TSUNAGI_ANKICONNECT_CHECKOUT to run upstream comparisons")
    return load_reference(checkout)


@pytest.fixture
def permission_pair(reference, monkeypatch):
    import aqt

    namespace = reference.handler.__func__.__globals__
    config = copy.deepcopy(namespace["util"].DEFAULT_CONFIG)
    writes, prompts = [], []
    choice = SimpleNamespace(button=1, ignore=False)

    def persist(value):
        writes.append(copy.deepcopy(value))
        config.update(copy.deepcopy(value))

    monkeypatch.setattr(namespace["util"], "setting", lambda key: config[key])
    monkeypatch.setitem(namespace, "aqt", SimpleNamespace(mw=SimpleNamespace(
        addonManager=SimpleNamespace(
            getConfig=lambda name: copy.deepcopy(config),
            writeConfig=lambda name, value: persist(value),
        ),
    )))
    monkeypatch.setattr(reference, "window", lambda: SimpleNamespace(windowIcon=lambda: None))

    def dialog_type(side):
        class Dialog:
            Icon = SimpleNamespace(Question=1)
            StandardButton = SimpleNamespace(Yes=1, No=2)

            def __init__(self, parent):
                prompts.append(side)

            def __getattr__(self, name):
                return lambda *args: None

            def exec(self):
                return choice.button

            def checkBox(self):
                return SimpleNamespace(isChecked=lambda: choice.ignore)

            @classmethod
            def question(cls, *args):
                prompts.append(side)
                return choice.button

        return Dialog

    qt = SimpleNamespace(WindowStaysOnTopHint=1)
    checkbox = lambda **kwargs: SimpleNamespace(isChecked=lambda: choice.ignore)
    monkeypatch.setitem(namespace, "QMessageBox", dialog_type("upstream"))
    monkeypatch.setitem(namespace, "QCheckBox", checkbox)
    monkeypatch.setitem(namespace, "Qt", qt)
    monkeypatch.setitem(sys.modules, "aqt.qt", SimpleNamespace(
        QMessageBox=dialog_type("shim"), QCheckBox=checkbox, Qt=qt,
    ))
    monkeypatch.setattr(aqt, "mw", SimpleNamespace(windowIcon=lambda: None))
    monkeypatch.setattr("tsunagi.adapters.ops.call_on_main", lambda fn, timeout: fn())
    shim_writes = []
    settings = Settings({
        "api_key": config["apiKey"],
        "cors_allowlist": copy.deepcopy(config["webCorsOriginList"]),
        "ankiconnect_ignore_origins": [],
    }, persist=lambda value: shim_writes.append(copy.deepcopy(value)))
    return SimpleNamespace(
        reference=reference, config=config, writes=writes, prompts=prompts,
        choice=choice, settings=settings, shim_writes=shim_writes,
    )


def compare_permission_state(pair, payload, *, origin=None, http=False):
    before = len(pair.prompts)
    if http:
        headers = {} if origin is None else {"Origin": origin}
        expected = pair.reference.http_raw_request(json.dumps(payload).encode(), headers=headers).json()
    else:
        expected = pair.reference.handler(copy.deepcopy(payload))
    expected_prompts = len(pair.prompts) - before
    actual = handle_ankiconnect_rpc(copy.deepcopy(payload), origin=origin, settings=pair.settings)
    assert actual == expected
    assert pair.prompts[before:] == ["upstream"] * expected_prompts + ["shim"] * expected_prompts
    assert pair.settings.get("cors_allowlist") == pair.config["webCorsOriginList"]
    assert pair.settings.get("ankiconnect_ignore_origins") == pair.config["ignoreOriginList"]
    assert len(pair.shim_writes) == len(pair.writes)
    for actual_write, expected_write in zip(pair.shim_writes, pair.writes):
        assert actual_write["cors_allowlist"] == expected_write["webCorsOriginList"]
        assert actual_write["ankiconnect_ignore_origins"] == expected_write["ignoreOriginList"]


@pytest.mark.parametrize("origin", [
    None, "", 0, False, [], {}, 42, ["site"], {"site": "value"},
    "http://localhost", "https://unknown.test",
])
@pytest.mark.parametrize("button,ignore", [(1, False), (1, True), (2, False), (2, True), (0, True)])
def test_nested_permission_persistence(permission_pair, origin, button, ignore):
    pair = permission_pair
    pair.choice.button, pair.choice.ignore = button, ignore
    payload = {"action": "multi", "version": 6, "params": {"actions": [
        {"action": "requestPermission", "version": 6, "params": {"origin": origin, "allowed": False}},
    ]}}
    # A second request proves duplicate acceptance writes and ignored-origin suppression.
    for _ in range(2):
        compare_permission_state(pair, payload)


@pytest.mark.parametrize("origin", [None, "", "http://localhost", "https://unknown.test"])
@pytest.mark.parametrize("button,ignore", [(1, False), (2, False), (2, True), (0, True)])
def test_http_permission_persistence(permission_pair, origin, button, ignore):
    pair = permission_pair
    pair.choice.button, pair.choice.ignore = button, ignore
    payload = {"action": "requestPermission", "version": 6}
    for _ in range(2):
        compare_permission_state(pair, payload, origin=origin, http=True)


@pytest.mark.parametrize("origin", [None, "", "https://unknown.test", ["site"]])
@pytest.mark.parametrize("allowed", [False, True])
def test_allowed_context_precedes_ignored_origin(permission_pair, origin, allowed):
    pair = permission_pair
    pair.config["ignoreOriginList"] = [origin]
    pair.config["apiKey"] = "test-key"
    pair.settings.configure({
        **pair.settings.snapshot(), "ankiconnect_ignore_origins": [origin], "api_key": "test-key",
    }, persist=pair.shim_writes.append)
    compare_permission_state(pair, {
        "action": "multi", "version": 6, "key": "test-key", "params": {"actions": [
            {"action": "requestPermission", "version": 6, "params": {"origin": origin, "allowed": allowed}},
        ]},
    })
    assert pair.prompts == []
