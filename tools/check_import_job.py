"""Verify a slow import job completes once through a real Qt CollectionOp."""
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

from qt_smoke import aqt, run, until


def check(app, screenshot):
    from aqt import gui_hooks

    from tsunagi.adapters import ops
    from tsunagi.adapters.anki import collection as adapter
    from tsunagi.adapters.events import ApiOp
    from tsunagi.adapters.jobs import jobs
    from tsunagi.http.v1 import collection as route
    from tsunagi.shared.schemas.collection import ExportRequest, ImportRequest

    col = aqt.mw.col
    note = col.new_note(col.models.by_name('Basic'))
    note['Front'] = 'slow import job'
    col.add_note(note, col.decks.id('Default'))
    release = Event()
    observed, calls = [], []
    original = adapter.import_package.__wrapped__

    def delayed(col, path, **options):
        calls.append(path)
        if not release.wait(5):
            raise RuntimeError('test did not release import')
        return original(col, path, **options)

    def changed(changes, initiator):
        if isinstance(initiator, ApiOp):
            observed.append(changes)

    with tempfile.TemporaryDirectory(prefix='tsunagi-job-package-') as folder:
        path = str(Path(folder) / 'test.apkg')
        with ThreadPoolExecutor(max_workers=1) as pool:
            export = pool.submit(route.export, ExportRequest(deck='Default', path=path))
            until(app, export.done)
            assert export.result().success
            col.remove_notes([note.id])
            gui_hooks.operation_did_execute.append(changed)
            try:
                with patch.object(ops, 'OP_TIMEOUT', 0.1), patch.object(
                    adapter.import_package, '__wrapped__', delayed
                ):
                    request = pool.submit(route.import_, ImportRequest(path=path))
                    until(app, request.done)
                    response = request.result()
                    assert response.status_code == 202
                    job_id = json.loads(response.body)['job_id']
                    until(app, lambda: jobs.snapshot(job_id)['status'] == 'running')
                    assert not observed
                    release.set()
                    until(app, lambda: jobs.snapshot(job_id)['status'] == 'done')
                    assert jobs.snapshot(job_id)['result']['imported'] == 1
                    assert len(calls) == 1
                    assert observed and observed[-1].note
                    assert col.note_count() == 1
                    col.undo()
                    assert col.note_count() == 0
            finally:
                release.set()
                gui_hooks.operation_did_execute.remove(changed)
    print('PASS: 202 tracks one import; completion counts, change notification and undo preserved.', flush=True)


if __name__ == '__main__':
    run(check, __doc__)
