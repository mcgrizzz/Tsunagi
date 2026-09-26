"""Anki-side changes are collected into bursts and itemized by one scan."""
import time

import pytest
from anki.collection import OpChanges

from tsunagi.adapters.change_scan import OP_DELAY, TYPING_DELAY, ChangeScan
from tsunagi.adapters.events import ApiOp, broker, dispatch_op

pytestmark = pytest.mark.usefixtures("review_events")


def add(col, front):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"], note["Back"] = front, "x"
    return note, col.add_note(note, col.decks.id("Default")).changes


@pytest.fixture
def scan(col):
    kept, _ = add(col, "kept")
    doomed, _ = add(col, "doomed")
    time.sleep(1.05)  # `mod` has one-second resolution; start after these rows
    broker.start_session(col)
    delays = []
    broker.scanner = ChangeScan(col, delays.append)
    token = broker.subscribe()

    def flush():
        broker.scanner.flush()
        return {e["type"]: e.get("ids") for e in broker.drain(token)}

    yield col, kept, doomed, delays, flush
    broker.begin_drain()


def test_one_burst_itemizes_edits_adds_reviews_and_deletions(scan, answer_cards):
    col, kept, doomed, delays, flush = scan
    doomed_cards = doomed.card_ids()
    kept["Back"] = "typed"
    dispatch_op(col.update_note(kept), object())                  # editor save while typing
    new, changes = add(col, "new")
    dispatch_op(changes, object())                                 # Add dialog
    assert answer_cards(1) == 1                                    # reviewer: kept's card
    dispatch_op(OpChanges(card=True, study_queues=True), object())
    dispatch_op(col.remove_notes([doomed.id]).changes, object())  # Browser delete
    assert delays == [TYPING_DELAY, OP_DELAY, OP_DELAY, OP_DELAY]

    events = flush()
    assert events["notes.updated"] == [kept.id]
    assert events["notes.created"] == [new.id]
    assert events["notes.deleted"] == [doomed.id]
    assert events["cards.created"] == new.card_ids()
    assert events["cards.updated"] == kept.card_ids()
    assert events["cards.deleted"] == doomed_cards
    assert len(events["reviews.created"]) == 1
    assert "notes.stale" not in events and "cards.stale" not in events
    assert flush() == {}  # the burst was consumed


def test_rows_the_api_reported_are_not_repeated(scan):
    col, kept, doomed, _, flush = scan
    kept["Back"] = "api"
    op = ApiOp(collection=col)
    op.changes = {"notes": {"updated": [kept.id]}, "cards": {"deleted": doomed.card_ids()}}
    col.update_note(kept)
    col.remove_notes([doomed.id])
    dispatch_op(OpChanges(note=True, card=True), op)
    assert flush()["notes.updated"] == [kept.id]  # the API op's own events
    dispatch_op(OpChanges(tag=True), object())    # a later Anki-side change scans
    events = flush()
    assert "notes.updated" not in events and "cards.deleted" not in events
    assert events["notes.deleted"] == [doomed.id]  # the API op did not announce it


def test_undo_restoring_old_rows_falls_back_to_stale(scan):
    col, kept, _, _, flush = scan
    kept["Back"] = "undo me"
    dispatch_op(col.update_note(kept), object())
    assert flush()["notes.updated"] == [kept.id]
    dispatch_op(col.undo().changes, None)
    assert flush()["notes.stale"] is None


def test_late_timer_after_the_session_ends_publishes_nothing(scan):
    scanner = broker.scanner
    dispatch_op(OpChanges(note=True, tag=True), object())
    broker.begin_drain()
    scanner.flush()
    assert broker.scanner is None
