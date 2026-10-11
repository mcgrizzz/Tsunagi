"""The server's own check for Anki's day changing (R22, 6.117): at each
cutoff, after a config change, and on Anki's hook, each change sent once."""
import time
from types import SimpleNamespace

import pytest
from anki.collection import OpChanges

from tsunagi.adapters.day_change import MARGIN, DayWatch, check_after
from tsunagi.adapters.events import broker


@pytest.fixture(autouse=True)
def clean_broker():
    broker.reset()
    yield
    broker.reset()


@pytest.fixture
def watch():
    """A watch over a stand-in collection: the day and its cutoff are set by hand."""
    col = SimpleNamespace(sched=SimpleNamespace(today=10, day_cutoff=int(time.time()) + 3600))
    delays, counts = [], []
    broker.scanner = SimpleNamespace(mark_counts=lambda: counts.append(True))
    broker.day_watch = DayWatch(col, delays.append)
    token = broker.subscribe()

    def sent():
        return [e["type"] for e in broker.drain(token)]

    return col, delays, counts, sent


def test_it_waits_for_the_cutoff(watch):
    col, delays, _, _ = watch
    assert abs(delays[-1] - (col.sched.day_cutoff - time.time() + MARGIN)) < 2


def test_a_new_day_is_sent_once_with_counts_and_the_next_cutoff(watch):
    col, delays, counts, sent = watch
    col.sched.today, col.sched.day_cutoff = 11, col.sched.day_cutoff + 86400
    broker.day_watch.check()   # the timer
    broker.day_watch.check()   # Anki's hook, for the same day
    assert sent() == ["day.changed"]
    assert counts == [True]
    assert delays[-1] > 86400


def test_a_later_hour_stepping_the_day_back_is_sent(watch):
    col, _, _, sent = watch
    col.sched.today = 9
    check_after(OpChanges(config=True))
    assert sent() == ["day.changed"]


def test_a_config_change_without_a_new_day_only_moves_the_timer(watch):
    col, delays, counts, sent = watch
    col.sched.day_cutoff += 7 * 3600
    check_after(OpChanges(config=True))
    assert sent() == [] and counts == []
    assert delays[-1] > 7 * 3600


def test_other_changes_dont_check(watch):
    col, delays, _, sent = watch
    col.sched.today = 11
    check_after(OpChanges(card=True, note=True))
    assert sent() == [] and len(delays) == 1


def test_an_earlier_sessions_timer_does_nothing(watch):
    col, delays, _, sent = watch
    old = broker.day_watch
    broker.day_watch = None
    col.sched.today = 11
    old.check()
    assert sent() == [] and len(delays) == 1


def set_rollover(col, hour):
    prefs = col.get_preferences()
    prefs.scheduling.rollover = hour
    return col.set_preferences(prefs)


def test_on_a_real_collection_a_later_hour_steps_the_day_back_and_moves_the_timer(col):
    """Days start at this hour, then at the next: Anki puts it back on
    yesterday (no hour can, from 23:00), and the timer follows its cutoff."""
    hour = time.localtime().tm_hour
    col.db.execute("update col set crt = crt - 10 * 86400")  # a collection 10 days old
    set_rollover(col, hour)  # a new hour also refreshes Anki's cached day
    delays = []
    broker.start_session(col)
    broker.day_watch = DayWatch(col, delays.append)
    token = broker.subscribe()
    assert 0 < delays[-1] <= 86400 + MARGIN
    before = col.sched.today
    check_after(set_rollover(col, (hour + 1) % 24))
    moved = col.sched.today != before
    assert moved or hour == 23
    assert [e["type"] for e in broker.drain(token)] == (["day.changed"] if moved else [])
    assert abs(delays[-1] - (col.sched.day_cutoff - time.time() + MARGIN)) < 2
