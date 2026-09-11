"""Interactive dispatch deadlines and cancellation, without real dialogs."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from queue import Queue
from threading import Event

import pytest

from tsunagi.adapters import ops
from tsunagi.shared.errors import AnkiBusyError


def test_expired_dispatch_never_opens_a_late_dialog(monkeypatch):
    queued = Queue()
    calls = []
    monkeypatch.setattr(ops, 'OP_TIMEOUT', 0)
    monkeypatch.setattr(ops.mw.taskman, 'run_on_main', queued.put)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(ops.call_on_main_interactive, lambda: calls.append('opened'))
        with pytest.raises(AnkiBusyError, match='dispatch timed out'):
            pending.result(timeout=2)
    queued.get_nowait()()
    assert calls == []


@pytest.mark.parametrize('fail', [False, True])
def test_accepted_interaction_outlives_dispatch_timeout(monkeypatch, fail):
    queued = Queue()
    opened, close = Event(), Event()
    monkeypatch.setattr(ops, 'OP_TIMEOUT', 0.1)
    monkeypatch.setattr(ops.mw.taskman, 'run_on_main', queued.put)

    def dialog():
        opened.set()
        assert close.wait(3), 'test did not close its simulated dialog'
        if fail:
            raise ValueError('dialog failed')
        return 'cancelled'

    with ThreadPoolExecutor(max_workers=2) as pool:
        request = pool.submit(ops.call_on_main_interactive, dialog)
        ui = pool.submit(queued.get(timeout=2))
        try:
            assert opened.wait(2)
            # More than the dispatch timeout passes after the UI accepts it.
            with pytest.raises(TimeoutError):
                request.result(timeout=0.2)
        finally:
            close.set()
        ui.result(timeout=2)
        if fail:
            with pytest.raises(ValueError, match='dialog failed'):
                request.result(timeout=2)
        else:
            assert request.result(timeout=2) == 'cancelled'


def test_enqueue_error_is_returned(monkeypatch):
    def fail(callback):
        raise RuntimeError('UI queue unavailable')
    monkeypatch.setattr(ops.mw.taskman, 'run_on_main', fail)
    with ThreadPoolExecutor() as pool:
        request = pool.submit(ops.call_on_main_interactive, lambda: None)
        with pytest.raises(RuntimeError, match='UI queue unavailable'):
            request.result(timeout=2)


def test_ui_thread_call_runs_inline(monkeypatch):
    def unexpected_queue(callback):
        pytest.fail('already on the UI thread')
    monkeypatch.setattr(ops.mw.taskman, 'run_on_main', unexpected_queue)
    assert ops.call_on_main_interactive(lambda: 'cancelled') == 'cancelled'
