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


def _counts_events(token):
    return [e for e in broker.drain(token) if e["type"] == "decks.counts"]


def test_an_answer_sends_one_counts_event_and_a_flag_change_none(scan, answer_cards):
    col, kept, _, _, _ = scan
    token = broker.subscribe(types=frozenset({"decks.counts"}))
    before = broker.scanner.counts[1]
    assert answer_cards(1) == 1
    dispatch_op(OpChanges(card=True, study_queues=True), object())
    dispatch_op(OpChanges(card=True, study_queues=True), object())  # same burst
    broker.scanner.flush()
    [event] = _counts_events(token)
    [deck] = event["decks"]
    assert deck["id"] == 1 and deck["new_count"] == before["new_count"] - 1
    assert deck["learn_count"] == before["learn_count"] + 1

    col.set_user_flag_for_cards(1, kept.card_ids())  # counts do not move
    dispatch_op(OpChanges(card=True), object())
    broker.scanner.flush()
    assert _counts_events(token) == []


def test_api_ops_and_rollover_queue_counts(scan):
    col, kept, _, delays, _ = scan
    token = broker.subscribe(types=frozenset({"decks.counts"}))
    col.sched.suspend_cards(kept.card_ids())
    dispatch_op(OpChanges(card=True, study_queues=True), ApiOp(collection=col))
    assert delays == [OP_DELAY]
    broker.scanner.flush()
    [event] = _counts_events(token)
    assert event["decks"][0]["new_count"] == 1
    broker.scanner.mark_counts()  # day_did_change; nothing moved
    broker.scanner.flush()
    assert _counts_events(token) == []


def test_counts_are_not_computed_without_a_listener(scan, monkeypatch):
    col, kept, _, _, _ = scan
    scanner = broker.scanner
    broker.start_session(col)  # drop the fixture's catch-all stream
    broker.scanner = scanner
    broker.subscribe(types=frozenset({"sync"}))
    monkeypatch.setattr(broker.scanner, "_counts", lambda: pytest.fail("computed"))
    dispatch_op(OpChanges(card=True, study_queues=True), object())
    broker.scanner.flush()
