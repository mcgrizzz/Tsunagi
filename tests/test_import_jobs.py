"""Slow imports keep one operation alive and expose its eventual outcome."""
import pytest

from tsunagi.adapters.jobs import jobs
from tsunagi.http.v1 import collection, fsrs


@pytest.fixture(autouse=True)
def clean_jobs():
    jobs.reset()
    yield
    jobs.reset()


@pytest.fixture()
def pending(monkeypatch):
    calls = []
    original = collection.submit_import_package

    def defer(path, **kwargs):
        calls.append((path, kwargs))

    monkeypatch.setattr(collection, 'submit_import_package', defer)
    monkeypatch.setattr(collection.ops, 'OP_TIMEOUT', 0)
    return calls, original


def package(client, col, tmp_path):
    note = col.new_note(col.models.by_name('Basic'))
    note['Front'] = 'import job note'
    col.add_note(note, col.decks.id('Default'))
    path = str(tmp_path / 'job.apkg')
    response = client.post('/v1/collection:export', json={'deck': 'Default', 'path': path})
    assert response.status_code == 200, response.text
    col.remove_notes([note.id])
    return path


def test_slow_import_returns_job_then_real_result_once(client, col, tmp_path, pending):
    calls, run = pending
    path = package(client, col, tmp_path)
    response = client.post('/v1/collection:import', json={
        'path': path, 'with_scheduling': False, 'update_notes': 'never',
    })
    assert response.status_code == 202
    body = response.json()
    assert 'imported' not in body
    assert response.headers['location'] == '/v1/jobs/' + body['job_id']
    assert len(calls) == 1
    assert col.note_count() == 0
    queued = client.get(response.headers['location']).json()
    assert queued['status'] == 'queued'
    assert queued['kind'] == 'import_package'
    assert queued['result'] is None
    path, options = calls[0]
    assert options['with_scheduling'] is False
    assert options['update_notes'] == 'never'
    run(path, **options)
    result = client.get(response.headers['location']).json()
    assert result['status'] == 'done'
    assert result['result']['imported'] == 1
    assert result['result']['updated'] == 0
    assert col.note_count() == 1
    # Polling never submits or imports again.
    assert client.get(response.headers['location']).json()['status'] == 'done'
    assert len(calls) == 1
    assert col.undo_status().undo
    col.undo()
    assert col.note_count() == 0


def test_quick_import_keeps_200_result(client, col, tmp_path):
    path = package(client, col, tmp_path)
    response = client.post('/v1/collection:import', json={'path': path})
    assert response.status_code == 200
    assert response.json()['imported'] == 1
    assert 'job_id' not in response.json()


def test_late_import_error_is_pollable(client, tmp_path, pending):
    calls, run = pending
    response = client.post('/v1/collection:import', json={'path': str(tmp_path / 'missing.apkg')})
    assert response.status_code == 202
    path, options = calls[0]
    run(path, **options)
    result = client.get(response.headers['location']).json()
    assert result['status'] == 'failed'
    assert result['error']
    assert result['result'] is None


@pytest.mark.parametrize('running', [False, True])
def test_import_does_not_use_fsrs_abort_or_progress(client, pending, monkeypatch, running):
    def forbidden(*args):
        pytest.fail('import job touched FSRS progress/abort')
    monkeypatch.setattr(fsrs.f, 'read_progress', forbidden)
    monkeypatch.setattr(fsrs.f, 'request_abort', forbidden)
    response = client.post('/v1/collection:import', json={'path': 'test.apkg'})
    calls, _ = pending
    if running:
        calls[0][1]['on_started']()
    poll = response.headers['location']
    result = client.get(poll).json()
    assert result['status'] == ('running' if running else 'queued')
    assert result['progress'] is None
    abort = client.post(poll + ':abort')
    assert abort.status_code == 409
    assert not jobs.abort_requested(response.json()['job_id'])
    assert client.get(poll).json()['status'] == result['status']


def test_conflict_is_rejected_before_a_second_import_starts(client, pending):
    calls, _ = pending
    first = client.post('/v1/collection:import', json={'path': 'first.apkg'})
    assert first.status_code == 202
    second = client.post('/v1/collection:import', json={'path': 'second.apkg'})
    assert second.status_code == 409
    assert len(calls) == 1


def test_import_conflicts_with_an_active_fsrs_job_before_submission(client, pending):
    jobs.create('compute_params')
    response = client.post('/v1/collection:import', json={'path': 'test.apkg'})
    assert response.status_code == 409
    assert pending[0] == []


def test_setup_failure_releases_job_slot(client, pending, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('failed to dispatch import')
    monkeypatch.setattr(collection, 'submit_import_package', fail)
    response = client.post('/v1/collection:import', json={'path': 'test.apkg'})
    assert response.status_code == 500
    assert jobs.create('compute_params').status == 'queued'


def test_import_after_collection_unloads_fails_without_writing(client, pending, monkeypatch):
    import aqt

    response = client.post('/v1/collection:import', json={'path': 'test.apkg'})
    calls, run = pending
    monkeypatch.setattr(aqt.mw, 'col', None)
    run(calls[0][0], **calls[0][1])
    result = jobs.snapshot(response.json()['job_id'])
    assert result['status'] == 'failed'
    assert result['result'] is None


def test_openapi_documents_both_response_shapes(client):
    responses = client.get('/openapi.json').json()['paths']['/v1/collection:import']['post']['responses']
    assert responses['200']['content']['application/json']['schema']['$ref'].endswith('/ImportResult')
    assert responses['202']['content']['application/json']['schema']['$ref'].endswith('/JobSubmitted')


def test_queued_import_cannot_move_to_another_profile(client, monkeypatch):
    from tsunagi.adapters import ops
    from tsunagi.adapters.anki import collection as adapter

    queued = []
    monkeypatch.setattr(ops, 'OP_TIMEOUT', 0)
    monkeypatch.setattr(ops.mw.taskman, 'run_on_main', queued.append)

    def forbidden(*args, **kwargs):
        pytest.fail('import ran against the replacement collection')
    monkeypatch.setattr(adapter.import_package, '__wrapped__', forbidden)
    response = client.post('/v1/collection:import', json={'path': 'test.apkg'})
    assert response.status_code == 202
    monkeypatch.setattr(ops.mw, 'col', object())
    assert len(queued) == 1
    queued.pop()()
    result = jobs.snapshot(response.json()['job_id'])
    assert result['status'] == 'failed'
    assert result['result'] is None
