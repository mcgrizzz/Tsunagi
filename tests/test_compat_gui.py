"""
guiBrowse: opens the Browser on the Qt main thread, searches, returns card ids.
The aqt dialog surface is stubbed per-test - the module itself must stay
importable with no Qt present.
"""
import sys
import types

import pytest


class FakeBrowser:
    def __init__(self, with_on_search=True):
        self.searched = []
        self.activated = False
        self.sorted_by = None
        line_edit = types.SimpleNamespace(setText=lambda t: self.searched.append(t))
        self.form = types.SimpleNamespace(
            searchEdit=types.SimpleNamespace(lineEdit=lambda: line_edit))
        self.table = types.SimpleNamespace(
            _model=types.SimpleNamespace(
                active_column_index=lambda col: 3 if col == "cardDue" else None),
            _on_sort_column_changed=lambda idx, order: setattr(self, "sorted_by", (idx, order)),
        )
        if with_on_search:
            self.onSearch = lambda: None
        else:
            self.onSearchActivated = lambda: setattr(self, "activated", True)


@pytest.fixture()
def browser(monkeypatch):
    """Install aqt.dialogs / aqt.qt just for this test."""
    import aqt

    b = FakeBrowser()
    opened = []
    dialogs = types.SimpleNamespace(open=lambda name, parent: (opened.append((name, parent)), b)[1])
    monkeypatch.setattr(aqt, "dialogs", dialogs, raising=False)

    qt_mod = types.ModuleType("aqt.qt")
    qt_mod.Qt = types.SimpleNamespace(
        SortOrder=types.SimpleNamespace(AscendingOrder="asc", DescendingOrder="desc"))
    monkeypatch.setitem(sys.modules, "aqt.qt", qt_mod)

    b.opened = opened
    b.activateWindow = lambda: setattr(b, "activated", True)
    return b


def rpc(client, params=None):
    body = {"action": "guiBrowse", "version": 6}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


class TestGuiBrowse:
    def test_opens_searches_and_returns_card_ids(self, client, browser):
        client.post("/", json={"action": "addNote", "version": 6, "params": {"note": {
            "deckName": "Default", "modelName": "Basic", "fields": {"Front": "犬"}}}})
        resp = rpc(client, {"query": "犬"})
        assert resp["error"] is None
        assert browser.opened[0][0] == "Browser"
        assert browser.searched == ["犬"]
        assert resp["result"] and all(isinstance(c, int) for c in resp["result"])

    def test_no_query_returns_empty_and_does_not_search(self, client, browser):
        resp = rpc(client, {})
        assert resp["result"] == []
        assert browser.searched == []

    def test_reorder_not_a_dict(self, client, browser):
        resp = rpc(client, {"query": "x", "reorderCards": 5})
        assert resp["error"] == "reorderCards should be a dict: 5"

    def test_reorder_missing_keys(self, client, browser):
        resp = rpc(client, {"query": "x", "reorderCards": {"columnId": "cardDue"}})
        # Canonical's message, unbalanced quote included
        assert resp["error"] == 'Must provide a "columnId" and a "order" property"'

    def test_reorder_invalid_order(self, client, browser):
        resp = rpc(client, {"query": "x", "reorderCards": {
            "columnId": "cardDue", "order": "sideways"}})
        assert resp["error"] == "invalid card order: sideways"

    def test_reorder_invalid_column(self, client, browser):
        resp = rpc(client, {"query": "x", "reorderCards": {
            "columnId": "nope", "order": "ascending"}})
        assert resp["error"] == "invalid columnId: nope"

    def test_reorder_applies(self, client, browser):
        rpc(client, {"query": "x", "reorderCards": {"columnId": "cardDue", "order": "descending"}})
        assert browser.sorted_by == (3, "desc")


def test_modules_import_without_qt():
    # No aqt.dialogs / aqt.qt installed here: every Qt import is function-local,
    # which is what lets the addon load before Anki has a main window.
    import tsunagi.adapters.anki.gui as adapter
    import tsunagi.adapters.events as events
    import tsunagi.adapters.settings_dialog as settings_dialog
    import tsunagi.http.compat.actions.gui as compat
    import tsunagi.http.v1.events as events_routes
    import tsunagi.http.v1.gui as routes

    assert hasattr(compat, "ac_guiBrowse")
    assert hasattr(adapter, "open_browser") and hasattr(adapter, "current_card")
    assert hasattr(routes, "router")
    assert hasattr(settings_dialog, "open_settings")
    assert hasattr(events, "broker") and hasattr(events_routes, "router")


def test_every_gui_action_is_registered():
    from tsunagi.http.compat.registry import registry

    expected = {
        "guiBrowse", "guiSelectCard", "guiSelectNote", "guiSelectedNotes",
        "guiEditNote", "guiAddCards", "guiAddNoteSetData", "guiCurrentCard",
        "guiStartCardTimer", "guiShowQuestion", "guiShowAnswer", "guiAnswerCard",
        "guiUndo", "guiDeckOverview", "guiDeckBrowser", "guiDeckReview",
        "guiImportFile", "guiExitAnki", "guiCheckDatabase", "guiReviewActive",
        "guiPlayAudio",
    }
    assert expected <= set(registry._handlers)


def test_native_gui_routes_are_mounted():
    """
    The GUI needs a live main window to *do* anything, but /v1 must still
    expose it - a native client should never have to fall back to the shim.
    """
    from tsunagi.app import app

    paths = {r.path for r in app.routes}
    assert {"/v1/gui:browse", "/v1/gui:add-cards", "/v1/gui:answer-card",
            "/v1/gui:deck-review", "/v1/gui/current-card",
            "/v1/gui/selected-notes"} <= paths


def test_gui_edit_note_uses_standalone_but_native_uses_browser(client, col, monkeypatch):
    import sys
    from types import SimpleNamespace

    import aqt

    from tsunagi.adapters.anki import gui

    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "standalone routing test"
    col.add_note(note, col.decks.id("Default"))
    opened, browsed = [], []
    monkeypatch.setitem(sys.modules, "tsunagi.http.compat.edit_dialog", SimpleNamespace(
        open_editor=lambda nid: opened.append(col.get_note(nid).id),
    ))
    monkeypatch.setattr(gui, "call_on_main", lambda callback: callback())
    monkeypatch.setattr(gui, "_browse", lambda query, reorder: browsed.append(query))
    monkeypatch.setattr(aqt, "mw", SimpleNamespace(col=col), raising=False)
    reply = client.post("/", json={"action": "guiEditNote", "version": 6, "params": {"note": note.id}}).json()
    assert reply == {"result": None, "error": None}
    assert opened == [note.id]
    assert browsed == []
    assert gui.edit_note(note.id) is True
    assert browsed == [f"nid:{note.id}"]


def test_gui_edit_note_missing_id_reports_backend_error(client, col, monkeypatch):
    import sys
    from types import SimpleNamespace

    from anki.errors import NotFoundError

    from tsunagi.adapters.anki import gui

    monkeypatch.setitem(sys.modules, "tsunagi.http.compat.edit_dialog", SimpleNamespace(open_editor=col.get_note))
    monkeypatch.setattr(gui, "call_on_main", lambda callback: callback())
    try:
        col.get_note(0)
    except NotFoundError as exc:
        expected = str(exc)
    reply = client.post("/", json={"action": "guiEditNote", "version": 6, "params": {"note": 0}}).json()
    assert reply == {"result": None, "error": expected}


@pytest.mark.parametrize("value", [0, {}])
def test_gui_browse_passes_raw_text_to_qt_before_sort_validation(client, browser, monkeypatch, value):
    seen = []

    def reject_text(text):
        seen.append(text)
        raise TypeError("Qt rejected search text")

    monkeypatch.setattr(browser.form.searchEdit.lineEdit(), "setText", reject_text)
    reply = rpc(client, {"query": value, "reorderCards": False})
    assert reply == {"result": None, "error": "Qt rejected search text"}
    assert browser.activated
    assert seen == [value]
    assert type(seen[0]) is type(value)
    assert browser.sorted_by is None


def test_gui_browse_keeps_backend_search_error(client, col, browser):
    query = "("
    with pytest.raises(Exception) as caught:
        col.find_cards(query)
    reply = rpc(client, {"query": query})
    assert reply == {"result": None, "error": str(caught.value)}
    assert browser.searched == [query]


def test_gui_browse_searches_and_sorts_before_reading_ids(client, col, browser, monkeypatch):
    events = []
    monkeypatch.setattr(browser, "onSearch", lambda: events.append("search"))
    monkeypatch.setattr(browser.table, "_on_sort_column_changed", lambda *_: events.append("sort"))

    def find(query):
        events.append("find")
        return [123]

    monkeypatch.setattr(col, "find_cards", find)
    reply = rpc(client, {"query": "test", "reorderCards": {"columnId": "cardDue", "order": "ascending"}})
    assert reply == {"result": [123], "error": None}
    assert events == ["search", "sort", "find"]


def test_gui_browse_supports_search_activated(client, browser, monkeypatch):
    events = []
    monkeypatch.delattr(browser, "onSearch")
    monkeypatch.setattr(browser, "onSearchActivated", lambda: events.append("search"), raising=False)
    assert rpc(client, {"query": "cid:0"}) == {"result": [], "error": None}
    assert events == ["search"]


@pytest.mark.parametrize("action,parameter", [("guiSelectCard", "card"), ("guiSelectNote", "note")])
@pytest.mark.parametrize("value", [None, "123", 1.5])
@pytest.mark.parametrize("opened", [False, True])
def test_gui_selection_keeps_raw_id_and_closed_browser_result(client, browser, monkeypatch, action, parameter, value, opened):
    import aqt

    events = []
    monkeypatch.setattr(aqt.dialogs, "_dialogs", {"Browser": (None, browser if opened else None)}, raising=False)
    monkeypatch.setattr(browser.table, "clear_selection", lambda: events.append("clear"), raising=False)
    monkeypatch.setattr(browser.table, "select_single_card", lambda card: events.append(card), raising=False)
    reply = client.post("/", json={"action": action, "version": 6, "params": {parameter: value}}).json()
    assert reply == {"result": opened, "error": None}
    assert events == (["clear", value] if opened else [])
    if opened:
        assert type(events[-1]) is type(value)
    assert browser.opened == []


def test_gui_selection_keeps_clear_before_table_error(client, browser, monkeypatch):
    import aqt

    events = []
    monkeypatch.setattr(aqt.dialogs, "_dialogs", {"Browser": (None, browser)}, raising=False)
    monkeypatch.setattr(browser.table, "clear_selection", lambda: events.append("clear"), raising=False)

    def reject(card):
        events.append(card)
        raise TypeError("Browser rejected card ID")

    monkeypatch.setattr(browser.table, "select_single_card", reject, raising=False)
    reply = client.post("/", json={"action": "guiSelectCard", "version": 6, "params": {"card": []}}).json()
    assert reply == {"result": None, "error": "Browser rejected card ID"}
    assert events == ["clear", []]
