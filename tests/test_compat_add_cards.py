"""Focused Add Cards regressions; no live windows or upstream checkout needed."""
import base64
from types import SimpleNamespace

import pytest


def rpc(client, action, **params):
    return client.post('/', json={'action': action, 'version': 6, 'params': params}).json()


@pytest.fixture()
def add_dialog(monkeypatch, col):
    import aqt

    events = []
    editor = SimpleNamespace(note=col.new_note(col.models.by_name('Basic')))
    editor.note['Front'] = 'original'
    editor.note.tags = ['old']
    editor.set_note = lambda note: (events.append('set_note'), setattr(editor, 'note', note))
    editor.loadNote = lambda: events.append('load')
    dialog = SimpleNamespace(
        editor=editor,
        activateWindow=lambda: events.append('activate'),
        setAndFocusNote=lambda note: events.append('focus'),
        set_deck=lambda did: events.append(('deck', did)),
        set_note_type=lambda mid: (
            events.append(('model', mid)),
            setattr(editor, 'note', col.new_note(col.models.get(mid))),
        ),
        closeWithCallback=lambda callback: callbacks.append(callback),
    )
    callbacks = []
    registry = {'AddCards': (None, dialog)}
    dialogs = SimpleNamespace(
        _dialogs=registry,
        open=lambda name, parent: (events.append('open'), dialog)[1],
    )
    monkeypatch.setattr(aqt, 'dialogs', dialogs, raising=False)
    return SimpleNamespace(dialog=dialog, editor=editor, events=events,
                           registry=registry, callbacks=callbacks)


@pytest.mark.parametrize('action', ['guiAddCards', 'guiAddNoteSetData'])
def test_gui_attachments_reach_media_store_and_editor(client, col, add_dialog, action):
    add_dialog.registry['AddCards'] = (None, None) if action == 'guiAddCards' else (None, add_dialog.dialog)
    payload = {'deckName': 'Default', 'modelName': 'Basic', 'fields': {'Front': 'media'},
               'audio': {'filename': 'gui-test.mp3', 'data': base64.b64encode(b'gui audio').decode(),
                         'fields': ['Front']}}
    reply = rpc(client, action, note=payload)
    assert reply['error'] is None
    assert add_dialog.editor.note['Front'] == 'media[sound:gui-test.mp3]'
    from pathlib import Path
    assert (Path(col.media.dir()) / 'gui-test.mp3').read_bytes() == b'gui audio'


@pytest.mark.parametrize('note', [None, [], {'fields': None}, {'audio': {'url': 'https://unused.invalid'}}])
def test_closed_add_dialog_ignores_payload_before_media(client, add_dialog, monkeypatch, note):
    from tsunagi.http.compat.actions import gui
    add_dialog.registry['AddCards'] = (None, None)
    monkeypatch.setattr(gui, '_media_of', lambda note: pytest.fail('closed dialog prepared media'))
    assert rpc(client, 'guiAddNoteSetData', note=note, append='raw') == {
        'result': {'error': 'Add Note dialog is not open', 'code': 1}, 'error': None}
    assert add_dialog.events == []


def test_add_cards_exact_field_names_and_async_refill(client, add_dialog):
    reply = rpc(client, 'guiAddCards', note={
        'deckName': 'Default', 'modelName': 'Basic',
        'fields': {'front': 'ignored', 'Back': 'kept', 'Unknown': 'ignored'},
    })
    assert reply == {'result': 0, 'error': None}
    assert add_dialog.editor.note['Front'] == 'original'
    assert add_dialog.events == []
    assert len(add_dialog.callbacks) == 1
    add_dialog.callbacks.pop()()
    assert add_dialog.editor.note['Front'] == ''
    assert add_dialog.editor.note['Back'] == 'kept'
    assert add_dialog.events == ['open', 'set_note', 'activate', 'open', 'focus']


@pytest.mark.parametrize('action', ['guiAddCards', 'guiAddNoteSetData'])
def test_null_fields_keeps_error_instead_of_becoming_empty(client, add_dialog, action):
    reply = rpc(client, action, note={'deckName': 'Default', 'modelName': 'Basic', 'fields': None})
    assert reply['error'] == "'NoneType' object has no attribute 'items'"
    assert 'load' not in add_dialog.events
    assert not add_dialog.callbacks


@pytest.mark.parametrize('tags', [None, 'raw tags', ['z', 'a', 'z']])
@pytest.mark.parametrize('action', ['guiAddCards', 'guiAddNoteSetData'])
def test_gui_replacement_tags_stay_raw(client, add_dialog, action, tags):
    reply = rpc(client, action, note={'deckName': 'Default', 'modelName': 'Basic', 'tags': tags})
    assert reply['error'] is None
    for callback in add_dialog.callbacks:
        callback()
    assert add_dialog.editor.note.tags == tags


@pytest.mark.parametrize('append', ['false', [], {'truthy': True}])
def test_gui_append_uses_python_truthiness(client, add_dialog, append):
    reply = rpc(client, 'guiAddNoteSetData', note={'fields': {'Front': 7}, 'tags': ['new']}, append=append)
    assert reply == {'result': True, 'error': None}
    assert add_dialog.editor.note['Front'] == ('original7' if append else 7)
    assert set(add_dialog.editor.note.tags) == ({'old', 'new'} if append else {'new'})


def test_gui_field_failure_preserves_prior_edit_and_skips_media_write(client, col, add_dialog):
    reply = rpc(client, 'guiAddNoteSetData', note={'fields': {'Front': 'changed', 'missing': 'bad'},
                'audio': {'filename': 'not-stored.mp3', 'data': 'YQ==', 'fields': ['Front']}})
    assert reply['error'] == 'Field "missing" not found in current note'
    assert add_dialog.editor.note['Front'] == 'changed'
    assert 'load' not in add_dialog.events
    from pathlib import Path
    assert not (Path(col.media.dir()) / 'not-stored.mp3').exists()


@pytest.mark.parametrize('note,error', [
    ([], "'list' object has no attribute 'get'"),
    (None, "argument of type 'NoneType' is not iterable"),
    (0, "argument of type 'int' is not iterable"),
])
def test_open_add_dialog_preserves_malformed_note_error(client, add_dialog, note, error):
    assert rpc(client, 'guiAddNoteSetData', note=note)['error'] == error
    assert 'load' not in add_dialog.events
