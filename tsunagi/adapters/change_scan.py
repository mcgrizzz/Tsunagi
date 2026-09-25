"""
Exact IDs for changes made inside Anki.

Anki reports which kinds of data an operation changed, not which rows. API
writes know their own IDs; everything else (the Browser, the editor, the Add
dialog, the reviewer, other add-ons) is collected into a burst. When the burst
goes quiet, one scan finds the rows: notes and cards by `mod`, review log rows
by ID, deletions from `graves`. A resource Anki flagged but the scan could not
itemize, such as rows an undo restored with their old `mod`, stays `.stale`.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Iterable, Set, Tuple

from .event_results import freeze_changes
from .events import affected_resources, broker

OP_DELAY = 0.5      # seconds of quiet before scanning after an operation
TYPING_DELAY = 2.0  # editor saves arrive while typing; wait for a pause
_GRAVE_RESOURCES = {0: "cards", 1: "notes"}
_GRAVE_TYPES = {name: kind for kind, name in _GRAVE_RESOURCES.items()}


class ChangeScan:
    def __init__(self, col: Any, restart_timer: Callable[[float], None]) -> None:
        self.col = col
        self.restart_timer = restart_timer  # (seconds); the timer calls flush()
        self.flags: Set[str] = set()
        # (resource, id) -> newest mod already reported
        self.seen: Dict[Tuple[str, int], int] = {}
        self.rebase()

    def rebase(self) -> None:
        """Start from now: at session start and after a sync."""
        self.since = int(time.time())
        self.graves = self._graves()

    def _graves(self) -> Set[Tuple[int, int]]:
        return {(int(oid), int(kind)) for oid, kind in
                self.col.db.all("select oid, type from graves")}

    def mark(self, flags: Iterable[str], *, typing: bool = False) -> None:
        self.flags.update(flags)
        self.restart_timer(TYPING_DELAY if typing else OP_DELAY)

    def reported(self, changes: Dict[str, Dict[str, list]]) -> None:
        """Rows an API write already announced; scans skip them unless changed again."""
        now = int(time.time())
        for resource, kinds in changes.items():
            for kind, ids in kinds.items():
                for rid in ids:
                    if kind != "deleted":
                        self.seen[(resource, int(rid))] = now
                    elif resource in _GRAVE_TYPES:
                        self.graves.add((int(rid), _GRAVE_TYPES[resource]))

    def scan(self) -> Dict[str, Dict[str, list]]:
        start = int(time.time())
        since_ms = self.since * 1000
        found: Dict[str, Dict[str, list]] = {}

        def add(resource: str, rid: int, mod: int, kind: str) -> None:
            if self.seen.get((resource, rid), -1) >= mod:
                return
            self.seen[(resource, rid)] = mod
            found.setdefault(resource, {}).setdefault(kind, []).append(rid)

        for table in ("notes", "cards"):
            for rid, mod in self.col.db.all(
                    f"select id, mod from {table} where mod >= ?", self.since):
                add(table, rid, mod, "created" if rid >= since_ms else "updated")
        for rid in self.col.db.list("select id from revlog where id >= ?", since_ms):
            add("reviews", rid, rid // 1000, "created")
        graves = self._graves()
        for oid, kind in graves - self.graves:
            if kind in _GRAVE_RESOURCES:
                found.setdefault(_GRAVE_RESOURCES[kind], {}).setdefault("deleted", []).append(oid)
        self.graves = graves
        self.since = start
        self.seen = {key: mod for key, mod in self.seen.items() if mod >= start}
        return found

    def flush(self) -> None:
        """Publish one burst. Called by the timer on the main thread."""
        flags, self.flags = sorted(self.flags), set()
        if broker.scanner is not self or not flags:
            return
        try:
            found = freeze_changes(self.scan())
        except Exception:
            found = {}  # collection closing: fall back to the flags alone
            logging.getLogger(__name__).debug("Change scan failed", exc_info=True)
        broker.publish("change", changes=found, origin="ui",
                       affected=affected_resources(flags), anki={"changes": flags})
