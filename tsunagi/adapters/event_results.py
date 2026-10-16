"""Bounded ID lists carried by completed collection operations.

Adapters describe created, updated, or deleted records by ID. No note fields,
card contents, or per-subscriber collection reads belong in event payloads.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable

MAX_RESULT_IDS = 1000


def note_result(note: Any, *, created: bool = False) -> dict:
    """Use the saved note's ID and, on creation, its generated card IDs."""
    result = {"notes": {"created" if created else "updated": [int(note.id)]}}
    if created:
        result["cards"] = {"created": list(note.cards or [])}
    return result


def card_changes(col: Any, where: str, *args: Any) -> Callable[[], dict]:
    """
    For a write that adds or removes cards as a side effect (6.96): read the
    cards `where` matches before it; the returned factory, called after it,
    names the cards since deleted, created, or moved to another deck or
    template; the notes deleted with their last card; and as updated, the
    notes that kept some of their cards or gained one (a note row lists them).
    """
    def rows(sql: str, *values: Any) -> Dict[int, tuple]:
        return {cid: (nid, did, ord) for cid, nid, did, ord in
                col.db.all(f"select id, nid, did, ord from cards where {sql}", *values)}

    before = rows(where, *args)

    def changes() -> dict:
        after = {**rows(where, *args), **rows("id in " + _ids(before))}
        created, deleted = after.keys() - before.keys(), before.keys() - after.keys()
        touched = {before[c][0] for c in deleted} | {after[c][0] for c in created}
        nids = {nid for nid, *_ in before.values()} | touched
        kept = set(col.db.list("select id from notes where id in " + _ids(nids)))
        return {"cards": {"created": sorted(created), "deleted": sorted(deleted),
                          "updated": sorted(c for c in before.keys() & after.keys()
                                            if before[c][1:] != after[c][1:])},
                "notes": {"deleted": sorted(nids - kept), "updated": sorted(touched & kept)}}
    return changes


def combined(factories: Iterable[Callable[[], dict]]) -> Callable[[], dict]:
    """One factory listing what each of several `card_changes` names, for a
    write that saves note types one by one (their cards don't overlap)."""
    factories = list(factories)

    def changes() -> dict:
        result: Dict[str, Dict[str, list]] = {}
        for factory in factories:
            for resource, kinds in factory().items():
                for kind, ids in kinds.items():
                    result.setdefault(resource, {}).setdefault(kind, []).extend(ids)
        return result
    return changes


def _ids(ids: Iterable[int]) -> str:
    return "(" + ",".join(str(int(i)) for i in ids) + ")"


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
