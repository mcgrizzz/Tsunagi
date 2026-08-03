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


def test_module_imports_without_qt():
    # No aqt.dialogs / aqt.qt installed here: all Qt imports are function-local
    import tsunagi.http.compat.actions.gui as gui
    assert hasattr(gui, "ac_guiBrowse")
