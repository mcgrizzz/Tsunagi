"""Bounded ID lists carried by completed collection operations.

Adapters identify which IDs to fetch or remove. No note fields, card contents,
or per-subscriber collection reads belong in event payloads.
"""
from __future__ import annotations

from typing import Any, Dict

MAX_RESULT_IDS = 1000


def note_result(note: Any, *, include_cards: bool = True) -> dict:
    """Use the saved note's ID and, on creation, its generated card IDs."""
    result = {"notes": {"fetch": [int(note.id)]}}
    if include_cards:
        result["cards"] = {"fetch": list(note.cards or [])}
    return result


def freeze_changes(changes: Dict[str, Any]) -> dict:
    """Detach ID lists before caller callbacks; large sets use refresh instead."""
    result = {}
    for resource, change in changes.items():
        if set(change) - {"fetch", "remove"}:
            raise ValueError("Event changes accept only fetch/remove IDs")
        fetch = list(dict.fromkeys(int(i) for i in change.get("fetch", [])))
        remove = list(dict.fromkeys(int(i) for i in change.get("remove", [])))
        if len(fetch) + len(remove) <= MAX_RESULT_IDS:
            result[resource] = {"fetch": fetch, "remove": remove}
    return result
