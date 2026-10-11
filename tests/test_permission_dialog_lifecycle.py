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
    on_shown = []  # what a test does once the dialog is up, run inside its own loop

    class Dialog(widgets.QDialog):
        def __init__(self, parent):
            super().__init__(parent)
            dialogs.append(self)

        def showEvent(self, event):
            super().showEvent(event)
            shown.set()
            for act in on_shown:
                core.QTimer.singleShot(0, lambda act=act: act(self))
            on_shown.clear()

    monkeypatch.setitem(sys.modules, "aqt.qt", SimpleNamespace(
        QMessageBox=MessageBox, QCheckBox=widgets.QCheckBox, Qt=core.Qt, QDialog=Dialog,
        QComboBox=widgets.QComboBox, QDialogButtonBox=widgets.QDialogButtonBox,
        QHBoxLayout=widgets.QHBoxLayout, QLabel=widgets.QLabel, QVBoxLayout=widgets.QVBoxLayout,
    ))
    yield SimpleNamespace(app=app, core=core, dialogs=dialogs, rejection_threads=rejection_threads,
                          events=events, shown=shown, on_shown=on_shown)
    for dialog in dialogs:
        dialog.close()
        dialog.deleteLater()
    app.processEvents()


def test_expired_request_closes_its_active_dialog_on_ui_thread(qt_host, monkeypatch):
    from tsunagi.adapters import ops

    qt = qt_host
    results, guard_fired = [], []
    original_wait = ops._wait

    def wait_after_visible(done, box, timeout, what, result_on_main=False):
        # Cold Qt/font initialization must not consume the active-dialog deadline.
        assert qt.shown.wait(timeout=5)
        return original_wait(done, box, 0.01, what, result_on_main)

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


# The access prompt (6.124), on real Qt widgets.
def answer_access(qt, act, request=None):
    """Show the access prompt, run `act(dialog)` on the UI thread once it's up, return the answer."""
    from tsunagi.adapters.access_requests import AccessAsk
    from tsunagi.adapters.dialogs import ask_access_dialog
    request = request or AccessAsk(origin="https://site.test", name="site.test", address=None, existing=None,
                                   roles=[("default", "Default"), ("read_only", "Read-only")], role="default")
    results = []
    qt.on_shown.append(act)  # the dialog runs its own loop: act from inside it
    worker = threading.Thread(target=lambda: results.append(ask_access_dialog(request, timeout=5)))
    worker.start()
    while worker.is_alive():
        qt.app.processEvents()
    worker.join(1)
    return results[0]


def button(dialog, text, widgets):
    return next(b for b in dialog.findChildren(widgets.QPushButton) if b.text() == text)


def test_allow_answers_the_role_chosen(qt_host):
    from PyQt6 import QtWidgets as widgets

    def act(dialog):
        dialog.findChild(widgets.QComboBox).setCurrentIndex(1)
        button(dialog, "Allow", widgets).click()
    decision = answer_access(qt_host, act)
    assert (decision.accepted, decision.role, decision.ignore) == (True, "read_only", False)


def test_enter_doesnt_allow(qt_host):
    from PyQt6 import QtCore as core
    from PyQt6 import QtGui as gui
    from PyQt6 import QtWidgets as widgets

    def act(dialog):
        assert button(dialog, "Don't allow", widgets).isDefault()
        assert not button(dialog, "Allow", widgets).isDefault()
        for kind in (core.QEvent.Type.KeyPress, core.QEvent.Type.KeyRelease):
            widgets.QApplication.sendEvent(dialog, gui.QKeyEvent(kind, core.Qt.Key.Key_Return,
                                                                 core.Qt.KeyboardModifier.NoModifier))
    assert not answer_access(qt_host, act).accepted


def test_dont_ask_again_with_dont_allow(qt_host):
    from PyQt6 import QtWidgets as widgets

    def act(dialog):
        dialog.findChild(widgets.QCheckBox).setChecked(True)
        button(dialog, "Don't allow", widgets).click()
    decision = answer_access(qt_host, act)
    assert (decision.accepted, decision.ignore) == (False, True)


def test_a_program_is_shown_unchecked_and_its_text_escaped(qt_host):
    from PyQt6 import QtWidgets as widgets

    from tsunagi.adapters.access_requests import AccessAsk
    seen = []

    def act(dialog):
        seen.extend(label.text() for label in dialog.findChildren(widgets.QLabel))
        dialog.reject()
    answer_access(qt_host, act, AccessAsk(origin=None, name="<i>Yomine</i>", address="192.168.1.5",
                                          existing=("<i>Yomine</i>", "Default"),
                                          roles=[("default", "Default")], role="default"))
    text = " ".join(seen)
    assert "&lt;i&gt;Yomine&lt;/i&gt;" in text and "<i>" not in text
    assert "192.168.1.5" in text and "can't check" in text and "new key" in text
