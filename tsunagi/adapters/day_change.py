"""
Anki's day changing (R22, 6.117). Searches relative to today (`is:due`,
`is:buried`, `rated:1`) then match other rows though none was written, so
change streams get `day.changed`, and `decks.counts` follows.

Anki's own `day_did_change` can't be relied on alone (26.08, 26.09; reported
upstream): it isn't fired while the reviewer is open, and its timer keeps the
old "next day starts at" hour after a change in Preferences or by sync. So the
server checks for itself: at each cutoff, after any operation that changed
config (Preferences and the reset after a sync both do), and on Anki's hook.
Every check compares the day number, so each change is sent once, whichever
check sees it first; a later hour can step the day back, and that is sent too.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from .events import DAY_CHANGED, broker

MARGIN = 1.0  # seconds past the cutoff, so the timer never wakes just before it


class DayWatch:
    def __init__(self, col: Any, restart_timer: Callable[[float], None]) -> None:
        self.col = col
        self.restart_timer = restart_timer  # (seconds); the timer calls check()
        self.day = col.sched.today
        self._arm()

    def check(self) -> None:
        """Main thread. Reading today also unburies, as Anki's own check does."""
        if broker.day_watch is not self:
            return  # an earlier session's timer
        try:
            day = self.col.sched.today
        except Exception:
            return  # collection closing
        if day != self.day:
            self.day = day
            broker.publish(DAY_CHANGED)
            if broker.scanner is not None:
                broker.scanner.mark_counts()
        self._arm()

    def _arm(self) -> None:
        self.restart_timer(max(self.col.sched.day_cutoff - time.time(), 0.0) + MARGIN)


def check_after(changes: Any) -> None:
    """An operation that changed config may have moved the day's start."""
    if broker.day_watch is not None and getattr(changes, "config", False):
        broker.day_watch.check()
