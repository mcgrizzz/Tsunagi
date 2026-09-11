"""Check import acknowledgement while a real Qt modal dialog stays open."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from qt_smoke import run, until


def check_mode(app, compat):
    from aqt.import_export import importing
    from aqt.qt import QDialog, QThread, QTimer

    from tsunagi.adapters import ops
    from tsunagi.adapters.anki import gui

    observations = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        def prompt(window):
            assert QThread.currentThread() == app.thread()
            dialog = QDialog(window)

            def cancel():
                observations.append((dialog.isVisible(), request.done()))
                dialog.reject()

            # Keep a genuine nested Qt event loop open past OP_TIMEOUT.
            QTimer.singleShot(300, cancel)
            dialog.exec()

        with patch.object(ops, 'OP_TIMEOUT', 0.1), patch.object(
            importing, 'prompt_for_file_then_import', prompt
        ):
            request = pool.submit(gui.import_file, _compat=compat)
            until(app, lambda: bool(observations) and request.done())
            assert request.result() is True
            assert observations == [(True, not compat)], observations
    print(f'PASS: compat={compat}; modal remained open beyond dispatch timeout; '
          f'response {"waited for cancellation" if compat else "acknowledged dispatch"}.', flush=True)


def check(app, screenshot):
    check_mode(app, False)
    check_mode(app, True)


if __name__ == '__main__':
    run(check, __doc__)
