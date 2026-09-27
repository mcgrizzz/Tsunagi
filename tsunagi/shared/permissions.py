"""
Permission names (backlog Part B 6.5a).

Every v1 route declares one with `openapi_extra=requires(...)`, which also
publishes it in the OpenAPI document as `x-permission`; every AnkiConnect
action declares one in `registry.register(..., permission=...)`. Nothing
enforces them yet. A group will grant a whole area ("write") or one name
("write:notes").
"""
from __future__ import annotations

from typing import Dict

PUBLIC = "public"  # reachable by anyone who can reach the server

_READ = ("notes", "cards", "decks", "deck_configs", "models", "tags", "reviews",
         "media", "collection", "addons")
_WRITE = ("notes", "cards", "decks", "deck_configs", "models", "tags", "reviews", "media")

PERMISSIONS = frozenset({
    PUBLIC,
    *(f"read:{r}" for r in _READ),
    *(f"write:{r}" for r in _WRITE),
    "write",  # routes that can change anything (undo)
    "gui",
    "sync",
    "manage",
    "memory_state",
    # Checked inside handlers or the event stream, not declared by a route.
    "local_files",
    "events:changes",
    "events:reviews",
})


def requires(permission: str) -> Dict[str, str]:
    """openapi_extra for a route that needs `permission`."""
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission {permission!r}")
    return {"x-permission": permission}
