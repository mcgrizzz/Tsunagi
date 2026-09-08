"""Real Qt regressions for HTTP waiters that outlive their permission dialogs.

Optional: install PyQt6 to run these without a display or an Anki GUI process.
"""

import sys
import threading
from types import SimpleNamespace

import pytest

from tsunagi.adapters.dialogs import PermissionDecision, ask_permission_dialog


@pytest.fixture
def qt_host(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    core = pytest.importorskip("PyQt6.QtCore", reason="optional real Qt lifecycle tests")
    gui = pytest.importorskip("PyQt6.QtGui")
    widgets = pytest.importorskip("PyQt6.QtWidgets")
    import aqt

    app = widgets.QApplication.instance() or widgets.QApplication([])
    events = []
    shown = threading.Event()

    class Taskman(core.QObject):
        queued = core.pyqtSignal(object)

        def __init__(self):
            super().__init__()
            self.queued.connect(self.run, core.Qt.ConnectionType.QueuedConnection)

        def run_on_main(self, callback):
            events.append(("queued", callback.__name__))
            self.queued.emit(callback)

        @core.pyqtSlot(object)
        def run(self, callback):
            events.append(("running", callback.__name__))
            callback()

    dialogs, rejection_threads = [], []

    class MessageBox(widgets.QMessageBox):
        def __init__(self, parent):
            super().__init__(parent)
            dialogs.append(self)

        def reject(self):
            events.append(("reject", threading.current_thread().name))
            rejection_threads.append(core.QThread.currentThread())
            super().reject()

        def showEvent(self, event):
            super().showEvent(event)
            shown.set()

    host = SimpleNamespace(taskman=Taskman(), windowIcon=gui.QIcon)
    monkeypatch.setattr(aqt, "mw", host)
    monkeypatch.setattr("tsunagi.adapters.ops.mw", host)
    monkeypatch.setitem(sys.modules, "aqt.qt", SimpleNamespace(
        QMessageBox=MessageBox, QCheckBox=widgets.QCheckBox, Qt=core.Qt,
    ))
    yield SimpleNamespace(app=app, core=core, dialogs=dialogs, rejection_threads=rejection_threads,
                          events=events, shown=shown)
    for dialog in dialogs:
        dialog.close()
        dialog.deleteLater()
    app.processEvents()


def test_expired_request_closes_its_active_dialog_on_ui_thread(qt_host, monkeypatch):
    from tsunagi.adapters import ops

    qt = qt_host
    results, guard_fired = [], []
    original_wait = ops._wait

    def wait_after_visible(done, box, timeout, what):
        # Cold Qt/font initialization must not consume the active-dialog deadline.
        assert qt.shown.wait(timeout=5)
        return original_wait(done, box, 0.01, what)

    monkeypatch.setattr(ops, "_wait", wait_after_visible)

    def release_orphan():
        guard_fired.append(True)
        for dialog in qt.dialogs:
            dialog.reject()

    # A broken implementation must fail promptly, not hang pytest in msg.exec().
    guard = qt.core.QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(release_orphan)
    guard.start(10000)
    worker = threading.Thread(target=lambda: results.append(
        ask_permission_dialog("https://timeout.test", timeout=0.2)))
    worker.start()
    try:
        while worker.is_alive():
            qt.app.processEvents()
        qt.app.processEvents()
        worker.join(timeout=1)
        assert not guard_fired, ("permission dialog survived emergency cleanup", qt.events, results)
        assert results == [PermissionDecision()]
        assert len(qt.dialogs) == 1
        assert not qt.dialogs[0].isVisible()
        assert qt.rejection_threads == [qt.app.thread()]
    finally:
        guard.stop()
        worker.join(timeout=1)


def test_expired_queued_request_never_opens_a_dialog(qt_host):
    results = []
    worker = threading.Thread(target=lambda: results.append(
        ask_permission_dialog("https://queued.test", timeout=0.01)))
    worker.start()
    # Deliberately hold the UI queue until the HTTP waiter has expired.
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert results == [PermissionDecision()]
    qt_host.app.processEvents()
    assert qt_host.dialogs == []
