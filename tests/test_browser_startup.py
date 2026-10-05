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

    monkeypatch.setattr(ops, "op_timeout", lambda: 0)
    rpc(client, {"query": "cid:0"})
    cold_browser.callbacks.pop()(False)
    [watchdog] = cold_browser.timers   # no retry is scheduled, only the deadline's
    assert cold_browser.searches == []
    assert "editor did not become ready" in caplog.text
    watchdog()   # already settled: nothing more happens
    assert cold_browser.searches == [] and cold_browser.callbacks == []


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


# The Tsunagi API's gui:browse answers once the Browser shows the search. The request
# thread waits; the editor's readiness arrives through callbacks, fired here as Qt would.

def _browse_in_background(client):
    import threading
    import time

    answer = {}
    thread = threading.Thread(target=lambda: answer.update(
        response=client.post("/v1/gui:browse", json={"query": "cid:0"})))
    thread.start()
    return thread, answer, time


def _wait_for(condition, time):
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "the request never reached the Browser"
        time.sleep(0.01)


def test_native_browse_answers_after_the_search(client, cold_browser):
    thread, answer, time = _browse_in_background(client)
    _wait_for(lambda: cold_browser.callbacks, time)
    assert thread.is_alive() and cold_browser.searches == []   # still waiting, Anki not blocked
    cold_browser.callbacks.pop()(True)
    thread.join(5)
    assert answer["response"].status_code == 200 and cold_browser.searches == [True]


def test_native_browse_ends_when_the_browser_closes(client, cold_browser):
    thread, answer, time = _browse_in_background(client)
    _wait_for(lambda: cold_browser.callbacks, time)
    cold_browser.browser = None
    cold_browser.callbacks.pop()(True)
    thread.join(5)
    assert answer["response"].status_code == 200 and cold_browser.searches == []


def test_native_browse_is_busy_when_the_editor_never_answers(client, cold_browser):
    # Qt can drop a pending callback (its page deleted): the deadline's timer ends the wait.
    thread, answer, time = _browse_in_background(client)
    _wait_for(lambda: cold_browser.timers, time)
    cold_browser.timers[0]()
    thread.join(5)
    assert answer["response"].status_code == 503 and cold_browser.searches == []
    cold_browser.callbacks.pop()(True)   # the editor gets ready later: the user still gets the search
    assert cold_browser.searches == [True]


def test_edit_note_answers_once_the_note_shows_and_focuses_its_editor(client, col, cold_browser, monkeypatch):
    import threading
    import time

    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "edit me"
    col.add_note(note, 1)
    focused = []
    monkeypatch.setattr(cold_browser.browser, "onNote", lambda: focused.append(list(cold_browser.searches)), raising=False)
    answer = {}
    thread = threading.Thread(target=lambda: answer.update(
        response=client.post("/v1/gui:edit-note", json={"note_id": note.id})))
    thread.start()
    _wait_for(lambda: cold_browser.callbacks, time)
    assert thread.is_alive() and focused == []
    cold_browser.callbacks.pop()(True)
    thread.join(5)
    assert answer["response"].status_code == 200
    assert focused == [[True]]   # Go > Note, after the search ran


def test_edit_note_for_a_missing_note_is_404_and_opens_nothing(client, cold_browser):
    assert client.post("/v1/gui:edit-note", json={"note_id": 123}).status_code == 404
    assert cold_browser.browser.opened == [] and cold_browser.callbacks == []
