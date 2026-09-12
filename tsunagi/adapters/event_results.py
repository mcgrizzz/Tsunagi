"""Bounded ID lists carried by completed collection operations.

Adapters describe created, updated, or deleted records by ID. No note fields,
card contents, or per-subscriber collection reads belong in event payloads.
"""
from __future__ import annotations

from typing import Any, Dict

MAX_RESULT_IDS = 1000


def note_result(note: Any, *, created: bool = False) -> dict:
    """Use the saved note's ID and, on creation, its generated card IDs."""
    result = {"notes": {"created" if created else "updated": [int(note.id)]}}
    if created:
        result["cards"] = {"created": list(note.cards or [])}
    return result


def freeze_changes(changes: Dict[str, Any]) -> dict:
    """Detach ID lists before caller callbacks; omit oversized details."""
    result = {}
    for resource, change in changes.items():
        if set(change) - {"created", "updated", "deleted"}:
            raise ValueError("Event changes accept only created/updated/deleted IDs")
        operations = {kind: list(dict.fromkeys(int(i) for i in ids))
                      for kind, ids in change.items()}
        if sum(len(ids) for ids in operations.values()) <= MAX_RESULT_IDS:
            result[resource] = {kind: ids for kind, ids in operations.items() if ids}
    return result
