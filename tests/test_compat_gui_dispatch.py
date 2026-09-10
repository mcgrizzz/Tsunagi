"""Import/check/exit dispatch tests; no real dialogs, repair or process exit."""
import sys
from types import ModuleType, SimpleNamespace

import pytest


def rpc(client, action, **params):
    return client.post('/', json={'action': action, 'version': 6, 'params': params}).json()


@pytest.fixture()
def dispatch(monkeypatch):
    import aqt

    events, callbacks = [], []
    state = SimpleNamespace(flags=2)
    def set_flags(flags):
        state.flags = flags
        events.append(('flags', flags))
    monkeypatch.setattr(aqt.mw, 'windowFlags', lambda: state.flags, raising=False)
    monkeypatch.setattr(aqt.mw, 'setWindowFlags', set_flags, raising=False)
    monkeypatch.setattr(aqt.mw, 'show', lambda: events.append('show'), raising=False)
    monkeypatch.setattr(aqt.mw, 'close', lambda: events.append('close'), raising=False)
    monkeypatch.setattr(aqt.mw, 'onCheckDB', lambda: events.append('check'), raising=False)
    importing = ModuleType('aqt.import_export.importing')
    importing.import_file = lambda mw, path: events.append(('import', path))
    importing.prompt_for_file_then_import = lambda mw: events.append('prompt')
    monkeypatch.setitem(sys.modules, 'aqt.import_export.importing', importing)
    qt = ModuleType('aqt.qt')
    qt.Qt = SimpleNamespace(WindowType=SimpleNamespace(WindowStaysOnTopHint=8))
    qt.QTimer = SimpleNamespace(singleShot=lambda delay, callback: (
        events.append(('timer', delay)), callbacks.append(callback)))
    monkeypatch.setitem(sys.modules, 'aqt.qt', qt)
    return SimpleNamespace(window=aqt.mw, events=events, callbacks=callbacks,
                           state=state, importing=importing, qt=qt)


@pytest.mark.parametrize('path', ['', 0, False, [], {}, 'C:/cards.apkg'])
def test_import_passes_explicit_raw_path_after_focus(client, dispatch, path):
    assert rpc(client, 'guiImportFile', path=path) == {'result': None, 'error': None}
    assert dispatch.events == [('flags', 10), 'show', ('flags', 2), 'show', ('import', path)]
    assert type(dispatch.events[-1][1]) is type(path)


@pytest.mark.parametrize('params', [{}, {'path': None}])
def test_import_prompts_only_for_omitted_or_null_path(client, dispatch, params):
    assert rpc(client, 'guiImportFile', **params) == {'result': None, 'error': None}
    assert dispatch.events[-1] == 'prompt'


@pytest.mark.parametrize('qt', [SimpleNamespace(WindowStaysOnTopHint=8), SimpleNamespace()])
def test_import_supports_old_or_absent_window_flag(client, dispatch, qt):
    dispatch.qt.Qt = qt
    assert rpc(client, 'guiImportFile', path='file.apkg')['error'] is None
    assert dispatch.events == ([('flags', 10), 'show', ('flags', 2), 'show']
                               if hasattr(qt, 'WindowStaysOnTopHint') else []) + [('import', 'file.apkg')]


def test_import_focus_failure_clears_topmost_flag_before_error(client, dispatch, monkeypatch):
    def show():
        dispatch.events.append('show')
        if dispatch.state.flags & 8:
            raise RuntimeError('show failed')
    monkeypatch.setattr(dispatch.window, 'show', show)
    assert rpc(client, 'guiImportFile', path='file.apkg') == {'result': None, 'error': 'show failed'}
    assert dispatch.state.flags == 2
    assert dispatch.events == [('flags', 10), 'show', ('flags', 2), 'show']


@pytest.mark.parametrize('action', ['guiImportFile', 'guiCheckDatabase', 'guiExitAnki'])
def test_gui_dispatch_preserves_original_errors(client, dispatch, monkeypatch, action):
    def fail(*args):
        raise RuntimeError('dispatch failed')
    if action == 'guiImportFile':
        monkeypatch.setattr(dispatch.importing, 'prompt_for_file_then_import', fail)
    elif action == 'guiCheckDatabase':
        monkeypatch.setattr(dispatch.window, 'onCheckDB', fail)
    else:
        monkeypatch.setattr(dispatch.qt.QTimer, 'singleShot', fail)
    assert rpc(client, action) == {'result': None, 'error': 'dispatch failed'}
    assert dispatch.callbacks == []


def test_check_database_calls_window_once(client, dispatch):
    assert rpc(client, 'guiCheckDatabase') == {'result': True, 'error': None}
    assert dispatch.events == ['check']


def test_exit_defers_close_until_after_response(client, dispatch):
    assert rpc(client, 'guiExitAnki') == {'result': None, 'error': None}
    assert dispatch.events == [('timer', 1000)]
    assert len(dispatch.callbacks) == 1
    dispatch.callbacks[0]()
    assert dispatch.events[-1] == 'close'


def test_native_empty_import_path_keeps_file_picker(dispatch):
    from tsunagi.adapters.anki import gui
    assert gui.import_file('') is True
    assert dispatch.events == ['prompt']
