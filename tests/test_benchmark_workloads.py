"""The end-to-end benchmark workloads give the same answer through both Tsunagi APIs.

Runs the real runner against the real app over HTTP, on a disposable collection
shaped like the testing profile (Kiku in a Mining deck). Timings here mean
nothing; the live desktop run is in docs/benchmarks.md.
"""
import asyncio
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn

from tools import benchmark_workloads as bw


@pytest.fixture()
def server(col, reset_settings, monkeypatch):
    import aqt

    from tsunagi.app import app
    monkeypatch.setattr(aqt.mw, "pm", SimpleNamespace(name="Bench"), raising=False)
    mm = col.models
    for note_type_name in (bw.MODEL, "Kiku+"):   # the profile also has a second note type
        model = mm.new(note_type_name)
        for name in (bw.TERM_FIELD, "ExpressionReading", "Sentence", "ExpressionAudio", "Picture"):
            mm.add_field(model, mm.new_field(name))
        template = mm.new_template("Card 1")
        template["qfmt"], template["afmt"] = "{{Expression}}", "{{Sentence}}"
        mm.add_template(model, template)
        mm.add(model)
    model, mining = mm.by_name(bw.MODEL), col.decks.id("Mining")
    for i in range(12):
        note = col.new_note(model)
        note[bw.TERM_FIELD] = f"word{i}"
        col.add_note(note, mining)
    # Saved under both note types, like よし: Yomitan lists both notes.
    old = col.new_note(mm.by_name("Kiku+"))
    old[bw.TERM_FIELD] = "word3"
    col.add_note(old, mining)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(5)


def run(url, implementation, tmp_path):
    report = {"workloads": []}
    args = SimpleNamespace(url=url, profile="Bench", implementation=implementation,
                           workloads=["mine_session", "client_settings", "sync_notes_batch", "first_page_cards",
                                      "known_words_snapshot", "mine_with_media"], repeats=1,
                           api_key_env="TSUNAGI_TEST_NO_KEY", output=tmp_path / f"{implementation}.json")
    asyncio.run(bw.run(args, report))
    assert report["completed"] and not any(report["leftovers"].values())
    return {e["workload"]: e for e in report["workloads"]}


def test_both_apis_give_the_same_answers_with_fewer_tsunagi_requests(server, tmp_path):
    native, shim = run(server, "native", tmp_path), run(server, "shim", tmp_path)
    for name in ("mine_session", "client_settings", "sync_notes_batch", "first_page_cards",
                 "known_words_snapshot", "mine_with_media"):
        assert native[name]["consistent_result"] and shim[name]["consistent_result"]
        assert native[name]["trials"][1].get("part_sha256") == shim[name]["trials"][1].get("part_sha256")
        assert native[name]["trials"][1]["result_sha256"] == shim[name]["trials"][1]["result_sha256"]
    # 10 popups, one word added from each: the check + the duplicates' notes + 2
    # (the note with its files, suspend) through /v1; 3 for the check + 5 through AnkiConnect.
    assert native["mine_session"]["trials"][1]["requests"] == 40
    assert shim["mine_session"]["trials"][1]["requests"] == 80
    assert (native["client_settings"]["trials"][1]["requests"],
            shim["client_settings"]["trials"][1]["requests"]) == (3, 3)
    # One mined note with audio and a picture: the note with its files through /v1;
    # two media stores and the note through AnkiConnect.
    assert (native["mine_with_media"]["trials"][1]["requests"],
            shim["mine_with_media"]["trials"][1]["requests"]) == (1, 3)
    # A 20-note file: deck check, then the notes with their pictures through /v1;
    # one multi through AnkiConnect.
    assert (native["sync_notes_batch"]["trials"][1]["requests"],
            shim["sync_notes_batch"]["trials"][1]["requests"]) == (2, 1)
    # The first 10 new cards and the total: the page, then every ID, in both.
    assert (native["first_page_cards"]["trials"][1]["requests"],
            shim["first_page_cards"]["trials"][1]["requests"]) == (2, 2)
    page = native["first_page_cards"]["result_sample"]
    assert page["total"] == 13 and len(page["cards"]) == 10 and page["cards"][0]["front"] == "word0"
    # Yomine's vocab: both mapped note types, only the fields it reads.
    vocab = native["known_words_snapshot"]["result_sample"]
    assert len(vocab) == 13 and {v["term"] for v in vocab.values()} == {f"word{i}" for i in range(12)}
    outcomes = native["sync_notes_batch"]["result_sample"]["outcomes"]
    assert outcomes == ["added"] * 15 + ["duplicate"] * 3 + ["empty", "rejected"]
