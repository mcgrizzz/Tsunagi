"""
Turning Tsunagi off in Tools -> Add-ons.

Anki unloads add-ons only when it restarts: toggleEnabled just writes the
add-on's meta.json, and no hook announces it. So without this the server kept
running, port and all, until the next restart. Kiso's Addon wraps
toggleEnabled (on_toggle in the root __init__.py) and calls ServerSwitch, which
lets the user stop it now instead, and start it again if they turn Tsunagi
back on in the same session.
"""
from typing import Any, Callable

TEXT = ("Tsunagi is turned off. Anki unloads add-ons only when it restarts, so "
        "Tsunagi's server keeps running until then.")


class ServerSwitch:
    """What turning Tsunagi off or on means for its running server."""

    def __init__(self, *, running: Callable[[], bool], ask_to_stop: Callable[[], bool],
                 stop: Callable[[], Any], start: Callable[[], Any]):
        self.running, self.ask_to_stop, self.stop, self.start = running, ask_to_stop, stop, start
        self.stopped_here = False

    def __call__(self, enabled: bool) -> None:
        if not enabled and self.running() and self.ask_to_stop():
            self.stop()
            self.stopped_here = True
        elif enabled and self.stopped_here:
            # Turned back on after stopping it here: run as if never turned off.
            self.stopped_here = False
            self.start()


def ask_to_stop(parent: Any) -> bool:
    """Qt prompt: True to stop the server now."""
    from aqt.qt import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle("Tsunagi")
    box.setText(TEXT)
    stop = box.addButton("Stop the server now", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Keep it running", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(stop)
    box.exec()
    return box.clickedButton() is stop
