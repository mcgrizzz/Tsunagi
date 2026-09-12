"""Report confirmed note creation from Anki's newer Add dialog.

Existing-note editor updates are deliberately not observed. The wrapper keeps
Anki's add result, failure handling, and collection lifecycle unchanged.
"""
from __future__ import annotations

import importlib
import logging
from functools import wraps
from typing import Any, Callable

from .events import broker, publish_note_added

log = logging.getLogger(__name__)


class UiEventObservers:
    def __init__(self, current_collection: Callable[[], Any]) -> None:
        self.current_collection = current_collection
        self.active = True
        self.patches: list[tuple[dict, str, Any, Any]] = []

    def _patch(self, namespace: dict, name: str, replacement: Any) -> None:
        original = namespace[name]
        namespace[name] = replacement
        self.patches.append((namespace, name, original, replacement))

    def uninstall(self) -> None:
        self.active = False
        for namespace, name, original, replacement in reversed(self.patches):
            # Another add-on may have wrapped us since installation. Leave its
            # wrapper intact; our now-inactive wrapper becomes a pass-through.
            if namespace.get(name) is replacement:
                namespace[name] = original
        self.patches.clear()

    def watch_add_note_handler(self, namespace: dict,
                               run_on_main: Callable[[Callable], Any]) -> None:
        from anki.notes_pb2 import AddNoteResponse

        original = namespace.get("addNote")
        if not callable(original):
            return

        @wraps(original)
        def observed():
            collection = None
            try:
                if self.active and broker.has_subscribers():
                    collection = self.current_collection()
            except Exception:
                log.debug("Cannot identify add-note collection", exc_info=True)
            output = original()  # preserve Anki's result and failures
            if collection is None:
                return output
            try:
                result = AddNoteResponse.FromString(output)
                changes = getattr(result.changes, "changes", result.changes)
                note_ids = [int(result.note_id)]

                def notify():
                    try:
                        if (self.active and collection is not None
                                and self.current_collection() is collection):
                            publish_note_added(note_ids, changes)
                    except Exception:
                        log.debug("Cannot publish added note", exc_info=True)

                run_on_main(notify)
            except Exception:
                log.debug("Cannot observe added note", exc_info=True)
            return output

        self._patch(namespace, "addNote", observed)


_observers: UiEventObservers | None = None


def uninstall() -> None:
    global _observers
    if _observers is not None:
        _observers.uninstall()
        _observers = None


def install() -> None:
    global _observers
    import aqt

    uninstall()
    observers = UiEventObservers(lambda: getattr(aqt.mw, "col", None))
    _observers = observers
    try:
        media = importlib.import_module("aqt.mediasrv")
        observers.watch_add_note_handler(
            media.post_handlers,
            lambda callback: aqt.mw.taskman.run_on_main(callback))
    except (ImportError, AttributeError):
        log.debug("Add-note observer unavailable", exc_info=True)
