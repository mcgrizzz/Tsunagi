"""Check GUI media callbacks and cancellation in an isolated real Qt profile."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import patch

from qt_smoke import aqt, run, until, wait_for_editor


def check(app, screenshot):
    from tsunagi.http.compat import downloads
    from tsunagi.http.compat.actions.gui import (
        GuiAddCardsParams,
        GuiAddNoteSetDataParams,
        ac_guiAddCards,
        ac_guiAddNoteSetData,
    )

    col = aqt.mw.col
    main_thread = get_ident()
    state = {"close": False}
    events = []
    original_write = col.media.write_data

    def write(filename, data, *args, **kwargs):
        assert get_ident() == main_thread, "GUI media accessed outside UI callback"
        events.append(("write", filename))
        if filename == "failed.mp3":
            raise OSError("storage failed")
        return original_write(filename, data, *args, **kwargs)

    def fetch(url):
        assert get_ident() != main_thread, "download blocks the UI thread"
        events.append(("fetch", url))
        done = Event()

        def ui_callback():
            if state["close"]:
                aqt.dialogs._dialogs["AddCards"][1].closeWithCallback(done.set)
            else:
                done.set()

        aqt.mw.taskman.run_on_main(ui_callback)
        assert done.wait(5), "UI callback blocked during download"
        return b"audio"

    def request(fn, params):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, params)
            until(app, future.done)
            return future.result()

    def saved(dialog):
        done = []
        dialog.editor.call_after_note_saved(lambda: done.append(True))
        until(app, lambda: bool(done))

    with patch.object(col.media, "write_data", write), patch.object(downloads, "download_media", fetch):
        assert request(ac_guiAddCards, GuiAddCardsParams(note={
            "deckName": "Default", "modelName": "Basic",
            "fields": {"Front": "Qt GUI media", "Back": ""},
            "audio": {"filename": "open.mp3", "url": "http://probe.invalid/open", "fields": ["Back"]},
        })) == 0
        dialog = aqt.dialogs._dialogs["AddCards"][1]
        wait_for_editor(app, dialog.editor)
        saved(dialog)
        assert dialog.editor.note["Back"] == "[sound:open.mp3]"
        assert events == [("fetch", "http://probe.invalid/open"), ("write", "open.mp3")]
        print("PASS: guiAddCards downloads off UI and prefills the real editor.", flush=True)

        events.clear()
        assert request(ac_guiAddNoteSetData, GuiAddNoteSetDataParams(note={
            "fields": {"Back": "updated"}, "audio": [
                {"filename": "prefix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
                {"filename": "failed.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
                {"filename": "suffix.mp3", "url": "http://probe.invalid/suffix", "fields": ["Back"]},
            ],
        })) is True
        saved(dialog)
        assert dialog.editor.note["Back"] == "updated[sound:prefix.mp3]storage failed[sound:suffix.mp3]"
        assert events == [
            ("write", "prefix.mp3"), ("write", "failed.mp3"),
            ("fetch", "http://probe.invalid/suffix"), ("write", "suffix.mp3"),
        ]
        print("PASS: GUI storage result precedes the next download; editor error text retained.", flush=True)

        # A pristine draft closes without asking to discard user content.
        dialog.editor.set_note(col.new_note(col.models.by_name("Basic")))
        wait_for_editor(app, dialog.editor)
        saved(dialog)
        state["close"] = True
        events.clear()
        result = request(ac_guiAddNoteSetData, GuiAddNoteSetDataParams(note={
            "fields": {}, "audio": [
                {"filename": "closed.mp3", "url": "http://probe.invalid/close", "fields": ["Back"]},
                {"filename": "unreachable.mp3", "url": "http://probe.invalid/unreachable", "fields": ["Back"]},
            ],
        }))
        assert result == {"error": "Add Note dialog is not open", "code": 1}
        assert events == [("fetch", "http://probe.invalid/close")]
        assert not Path(col.media.dir(), "closed.mp3").exists()
        assert not Path(col.media.dir(), "unreachable.mp3").exists()
        assert col.note_count() == 0
        print("PASS: closing during download cancels storage and later URLs; no notes added.", flush=True)


if __name__ == "__main__":
    run(check, __doc__)
