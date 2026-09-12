"""Observe confirmed editor saves without changing Anki's write operations.

Legacy editors use a CollectionOp factory; newer editors use Anki's local
protobuf handlers. These narrow adapters delegate the original call unchanged.
No editor selection, undo label, record cache or extra collection query is used
to infer identity. Unsupported paths retain general change notifications.
"""
from __future__ import annotations

import importlib
import logging
from functools import wraps
from typing import Any, Callable

from .events import broker, publish_note_change, ui_change_context

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

    def watch_editor_factory(self, namespace: dict) -> None:
        original = namespace.get("update_note")
        if not callable(original):
            return

        @wraps(original)
        def update_note(*args, **kwargs):
            operation = original(*args, **kwargs)
            if not self.active or not broker.has_subscribers():
                return operation
            try:
                note_id = int(kwargs["note"].id)
                run = operation._run
                if note_id <= 0 or not callable(run):
                    return operation

                @wraps(run)
                def tracked_run(mw, work, on_done):
                    collection = mw.col

                    def completed(future):
                        # Anki still owns success/failure callbacks and undo/UI
                        # handling. Read a completed future without changing it.
                        changes = None
                        try:
                            if (self.active and self.current_collection() is collection
                                    and future.exception() is None):
                                result = future.result()
                                candidate = getattr(result, "changes", result)
                                if getattr(candidate, "note", False):
                                    changes = candidate
                        except Exception:
                            log.debug("Cannot identify editor save", exc_info=True)
                        if changes is None:
                            return on_done(future)
                        with ui_change_context(changes, "notes.updated", [note_id]):
                            return on_done(future)

                    return run(mw, work, completed)

                operation._run = tracked_run
            except Exception:
                # A changed Anki factory contract costs enrichment, not a save.
                log.debug("Cannot observe editor operation", exc_info=True)
            return operation

        self._patch(namespace, "update_note", update_note)

    def watch_backend_handlers(self, namespace: dict, request_data: Callable[[], bytes],
                               run_on_main: Callable[[Callable], Any]) -> None:
        """Observe only the new editor's addNote/updateNotes protobuf boundary."""
        from anki.collection import OpChanges
        from anki.notes_pb2 import AddNoteResponse, UpdateNotesRequest

        for name in ("addNote", "updateNotes"):
            original = namespace.get(name)
            if not callable(original):
                continue

            def wrap(original, name):
                @wraps(original)
                def observed():
                    listening = False
                    collection = None
                    note_ids = []
                    try:
                        listening = self.active and broker.has_subscribers()
                        collection = self.current_collection() if listening else None
                        if listening and name == "updateNotes":
                            request = UpdateNotesRequest.FromString(request_data())
                            note_ids = [int(note.id) for note in request.notes]
                    except Exception:
                        listening = False
                        log.debug("Cannot identify editor request", exc_info=True)
                    # Preserve return bytes and failures exactly. Never emit on
                    # failure, including errors in Anki's own post-processing.
                    output = original()
                    if not listening:
                        return output
                    try:
                        if name == "addNote":
                            result = AddNoteResponse.FromString(output)
                            changes = result.changes
                            changes = getattr(changes, "changes", changes)
                            note_ids = [int(result.note_id)]
                            action = "notes.created"
                        else:
                            changes = OpChanges.FromString(output)
                            action = "notes.updated"

                        def notify():
                            try:
                                if (self.active and collection is not None
                                        and self.current_collection() is collection):
                                    publish_note_change(note_ids, action, changes)
                            except Exception:
                                log.debug("Cannot publish editor save", exc_info=True)

                        run_on_main(notify)
                    except Exception:
                        log.debug("Cannot observe editor response", exc_info=True)
                    return output

                return observed

            self._patch(namespace, name, wrap(original, name))


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
    # The legacy Editor's method uses its defining module's update_note alias.
    # Only patch that alias, never the shared operation factory or backend.
    try:
        editor = importlib.import_module("aqt.editor").Editor
        save = getattr(editor, "_save_current_note", None)
        namespace = getattr(save, "__globals__", {})
        observers.watch_editor_factory(namespace)
    except (ImportError, AttributeError):
        log.debug("Legacy editor observer unavailable", exc_info=True)
    try:
        media = importlib.import_module("aqt.mediasrv")
        observers.watch_backend_handlers(
            media.post_handlers, lambda: media.request.data,
            lambda callback: aqt.mw.taskman.run_on_main(callback))
    except (ImportError, AttributeError):
        log.debug("New editor observer unavailable", exc_info=True)
