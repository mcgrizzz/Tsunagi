"""Exercise staged media storage on real Anki workers in a disposable profile."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from unittest.mock import patch

from qt_smoke import run, until


def check(app, screenshot):
    import aqt

    from tsunagi.http.compat import downloads
    from tsunagi.http.compat.actions.notes import (
        AddNoteParams,
        ac_addNote,
        ac_canAddNoteWithErrorDetail,
    )

    col = aqt.mw.col
    main_thread = get_ident()
    original_write = col.media.write_data
    original_undo = col.undo_status()

    def check_case(case):
        events = []
        request_thread = []

        def write(filename, data, *args, **kwargs):
            assert get_ident() not in (main_thread, request_thread[0])
            events.append(("write", filename))
            if filename == "failed.mp3":
                raise OSError("simulated storage failure")
            return original_write(filename, data, *args, **kwargs)

        def fetch(url):
            assert get_ident() == request_thread[0]
            events.append(("fetch", "suffix.mp3"))
            # A UI callback must run while the request thread waits for I/O.
            ui_ran = Event()
            aqt.mw.taskman.run_on_main(ui_ran.set)
            assert ui_ran.wait(3), "UI blocked during media preparation"
            return b"suffix"

        def request():
            request_thread.append(get_ident())
            params = AddNoteParams(note={
                "modelName": "Basic", "deckName": "Default",
                "fields": {"Front": "worker media probe", "Back": ""},
                "audio": [
                    {"filename": "prefix.mp3", "data": "YXVkaW8=", "fields": ["Back"]},
                    {"filename": "failed.mp3", "data": "YXVkaW8=", "fields": None if case == "abort" else ["Back"]},
                    {"filename": "suffix.mp3", "url": "http://probe.invalid/suffix", "fields": ["Back"]},
                ],
            })
            return ac_addNote(params) if case == "add" else ac_canAddNoteWithErrorDetail(params)

        with patch.object(col.media, "write_data", write), patch.object(downloads, "download_media", fetch):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(request)
                until(app, future.done)
                reply = future.result()

        expected = [("write", "prefix.mp3"), ("write", "failed.mp3")]
        if case != "abort":
            expected += [("fetch", "suffix.mp3"), ("write", "suffix.mp3")]
        assert events == expected, events
        if case == "abort":
            assert reply == {"canAdd": False, "error": "'NoneType' object is not iterable"}, reply
        elif case == "continue":
            assert reply == {"canAdd": True}, reply
        else:
            assert col.get_note(reply)["Back"] == (
                "[sound:prefix.mp3]simulated storage failure[sound:suffix.mp3]"
            )
            col.undo()
        assert col.find_notes("") == []
        if case != "add":
            assert col.undo_status() == original_undo
        print(f"PASS: {case}; worker storage, request-thread downloads, single writes and note/undo state.", flush=True)

    for case in ("abort", "continue", "add"):
        check_case(case)


if __name__ == "__main__":
    run(check, __doc__)
