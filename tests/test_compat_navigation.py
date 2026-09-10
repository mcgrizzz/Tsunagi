"""Deck navigation and undo regressions without live window operations."""
from types import SimpleNamespace

import pytest


def rpc(client, action, **params):
    return client.post('/', json={'action': action, 'version': 6, 'params': params}).json()


@pytest.fixture()
def navigation(monkeypatch, col):
    import aqt

    events = []
    target = col.decks.id('Navigation::日本語')
    col.decks.select(1)
    monkeypatch.setattr(aqt.mw, 'onOverview', lambda: events.append(('overview', col.decks.selected())), raising=False)
    monkeypatch.setattr(aqt.mw, 'moveToState', lambda state: events.append((state, col.decks.selected())), raising=False)
    monkeypatch.setattr(aqt.mw, 'undo', lambda: events.append('undo'), raising=False)
    return SimpleNamespace(events=events, target=target, window=aqt.mw)


@pytest.mark.parametrize('action', ['guiDeckOverview', 'guiDeckReview'])
@pytest.mark.parametrize('name', [123, [], {}])
def test_navigation_keeps_raw_deck_name_error(client, col, navigation, action, name):
    col.decks.id('123')  # Coercing the numeric input could navigate to a real deck.
    selected = col.decks.selected()
    with pytest.raises(Exception) as expected:
        col.decks.by_name(name)
    assert rpc(client, action, name=name) == {'result': None, 'error': str(expected.value)}
    assert navigation.events == []
    assert col.decks.selected() == selected


@pytest.mark.parametrize('action', ['guiDeckOverview', 'guiDeckReview'])
@pytest.mark.parametrize('name', [None, 'not a navigation deck'])
def test_missing_deck_does_not_select_or_navigate(client, col, navigation, action, name):
    before = col.decks.selected()
    assert rpc(client, action, name=name) == {'result': False, 'error': None}
    assert col.decks.selected() == before
    assert navigation.events == []


@pytest.mark.parametrize('action,event', [('guiDeckOverview', 'overview'), ('guiDeckReview', 'review')])
def test_navigation_selects_deck_before_transition(client, navigation, action, event):
    assert rpc(client, action, name='Navigation::日本語') == {'result': True, 'error': None}
    # Direct review intentionally avoids the overview webview repaint race.
    assert navigation.events == [(event, navigation.target)]


@pytest.mark.parametrize('action,method', [('guiDeckOverview', 'onOverview'), ('guiDeckReview', 'moveToState')])
def test_navigation_failure_preserves_selection_and_error(client, col, navigation, monkeypatch, action, method):
    def fail(*args):
        raise RuntimeError('navigation failed')
    monkeypatch.setattr(navigation.window, method, fail)
    assert rpc(client, action, name='Navigation::日本語') == {'result': None, 'error': 'navigation failed'}
    assert col.decks.selected() == navigation.target


@pytest.mark.parametrize('action,method', [('guiDeckBrowser', 'moveToState'), ('guiUndo', 'undo')])
def test_browser_and_undo_preserve_callback_errors(client, navigation, monkeypatch, action, method):
    def fail(*args):
        raise RuntimeError('window callback failed')
    monkeypatch.setattr(navigation.window, method, fail)
    assert rpc(client, action) == {'result': None, 'error': 'window callback failed'}


def test_deck_browser_returns_null_and_keeps_selection(client, col, navigation):
    selected = col.decks.selected()
    assert rpc(client, 'guiDeckBrowser') == {'result': None, 'error': None}
    assert navigation.events == [('deckBrowser', selected)]
    assert col.decks.selected() == selected


def test_gui_undo_calls_window_once(client, navigation):
    assert rpc(client, 'guiUndo') == {'result': True, 'error': None}
    assert navigation.events == ['undo']
