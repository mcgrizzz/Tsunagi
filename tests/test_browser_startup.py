"""API searches wait for a cold editor without blocking the request."""

import sys
from types import ModuleType, SimpleNamespace

import pytest
from test_compat_gui import browser as browser
from test_compat_gui import rpc


@pytest.fixture
def cold_browser(browser, monkeypatch):
    from tsunagi.adapters.anki import gui

    callbacks, timers = [], []
    browser.editor = SimpleNamespace(web=SimpleNamespace(
        evalWithCallback=lambda script, callback: callbacks.append(callback),
    ))
    state = SimpleNamespace(browser=browser, callbacks=callbacks, timers=timers, searches=[])
    monkeypatch.setattr(gui, "_existing_dialog", lambda name: state.browser)
    monkeypatch.setattr(browser, "onSearch", lambda: state.searches.append(True))
    qt = sys.modules.get("aqt.qt") or ModuleType("aqt.qt")
    monkeypatch.setitem(sys.modules, "aqt.qt", qt)
    monkeypatch.setattr(qt, "QTimer", SimpleNamespace(singleShot=lambda delay, callback: timers.append(callback)), raising=False)
    return state


def test_cold_search_waits_then_warm_search_uses_normal_path(client, cold_browser):
    assert rpc(client, {"query": "cid:0"}) == {"result": [], "error": None}
    assert cold_browser.searches == []
    cold_browser.callbacks.pop()(False)
    assert cold_browser.searches == []
    cold_browser.timers.pop()()
    cold_browser.callbacks.pop()(True)
    assert cold_browser.searches == [True]
    assert rpc(client, {"query": "cid:0"}) == {"result": [], "error": None}
    assert cold_browser.searches == [True, True]
    assert cold_browser.callbacks == []


@pytest.mark.parametrize("change", ["closed", "replaced", "new_web", "new_request"])
def test_pending_search_is_cancelled_when_superseded(client, cold_browser, change):
    rpc(client, {"query": "cid:0"})
    first = cold_browser.callbacks.pop()
    if change == "closed":
        cold_browser.browser = None
    elif change == "replaced":
        cold_browser.browser = SimpleNamespace()
    elif change == "new_web":
        cold_browser.browser.editor.web = SimpleNamespace()
    else:
        rpc(client, {"query": "cid:1"})
    first(True)
    assert cold_browser.searches == []
    if change == "new_request":
        cold_browser.callbacks.pop()(True)
        assert cold_browser.searches == [True]


def test_unready_editor_stops_polling_at_operation_timeout(client, cold_browser, monkeypatch, caplog):
    from tsunagi.adapters import ops

    monkeypatch.setattr(ops, "OP_TIMEOUT", 0)
    rpc(client, {"query": "cid:0"})
    cold_browser.callbacks.pop()(False)
    assert cold_browser.timers == []
    assert cold_browser.searches == []
    assert "editor did not become ready" in caplog.text


def test_replaced_webview_gets_its_own_readiness_check(client, cold_browser):
    rpc(client, {"query": "cid:0"})
    cold_browser.callbacks.pop()(True)
    cold_browser.browser.editor.web = SimpleNamespace(
        evalWithCallback=lambda script, callback: cold_browser.callbacks.append(callback),
    )
    rpc(client, {"query": "cid:0"})
    assert cold_browser.searches == [True]
    cold_browser.callbacks.pop()(True)
    assert cold_browser.searches == [True, True]
