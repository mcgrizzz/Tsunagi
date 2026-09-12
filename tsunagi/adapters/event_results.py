"""Bounded, detached record changes carried by a completed collection operation.

Adapters declare only resources whose affected records they can identify. This
module never reads Anki: full records must already be part of the operation's
result; otherwise the adapter supplies IDs to fetch or IDs now absent.
"""
from __future__ import annotations

import json
from typing import Any, Dict

MAX_RESULT_BYTES = 64 * 1024
MAX_RESULT_IDS = 1000


def note_result(note: Any, *, include_cards: bool = True) -> dict:
    """Reuse the native save response, including its generated card IDs."""
    result = {"notes": {"upsert": [note.dict()]}}
    if include_cards:
        result["cards"] = {"fetch": list(note.cards or [])}
    return result


def freeze_changes(changes: Dict[str, Any]) -> dict:
    """Copy JSON data before success callbacks can mutate the returned DTO.

    Oversize snapshots become ID lookups; oversize ID sets lose their precise
    coverage and use the normal resource invalidation instead.
    """
    result = {}
    remaining = MAX_RESULT_BYTES - 2
    for resource, change in changes.items():
        upsert = change.get("upsert", [])
        fetch = list(dict.fromkeys(int(i) for i in change.get("fetch", [])))
        remove = list(dict.fromkeys(int(i) for i in change.get("remove", [])))
        if len(upsert) + len(fetch) + len(remove) > MAX_RESULT_IDS:
            continue
        item = {"upsert": upsert, "fetch": fetch, "remove": remove}
        encoded = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > remaining:
            item["fetch"] = list(dict.fromkeys(fetch + [int(r["id"]) for r in upsert]))
            item["upsert"] = []
            encoded = json.dumps(item, separators=(",", ":"))
        size = len(encoded.encode("utf-8")) + len(resource) + 4
        if size <= remaining:
            result[resource] = json.loads(encoded)
            remaining -= size
    return result
