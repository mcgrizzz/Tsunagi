"""
Permissions, roles and the caller of the current request (backlog 6.5a).

Every v1 route declares one permission with `openapi_extra=requires(...)`,
which also publishes it in the OpenAPI document as `x-permission`; every
AnkiConnect action declares one in `registry.register(..., permission=...)`.
Each app (and each of the two "No key" rows) has one role, and a role
grants whole areas ("write") or single names ("write:notes").
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional

PUBLIC = "public"  # reachable by anyone who can reach the server
# One add-on item (`addon:<provider>/<item>`, 2b-P). As a route's declaration
# it means the handler checks the item; as a grant, every approved item.
ADDON = "addon"

_READ = ("notes", "cards", "decks", "deck_presets", "note_types", "tags", "reviews",
         "media", "collection", "addons")
_WRITE = ("notes", "cards", "decks", "deck_presets", "note_types", "tags", "reviews", "media")

PERMISSIONS = frozenset({
    PUBLIC,
    *(f"read:{r}" for r in _READ),
    *(f"write:{r}" for r in _WRITE),
    "write",  # routes that can change anything (undo)
    "gui",
    "sync",
    "manage",
    "memory_state",
    ADDON,
    # Checked inside handlers or the event stream, not declared by a route.
    "local_files",
    "events:changes",
    "events:reviews",
})

# What a role may list: any permission, or a whole area. Roles may also list
# `addon:<provider>/<item>` names, which come from the providers (is_grant).
GRANTS = (PERMISSIONS - {PUBLIC}) | {p.split(":", 1)[0] for p in PERMISSIONS - {PUBLIC}}

NO_ACCESS = "none"
BUILTIN_ROLES: Dict[str, Dict] = {
    # Everything any AnkiConnect client can do, so swapping it in just works.
    "default": {"name": "Default",
                "grants": ["read", "write", "gui", "sync", "manage", "events:changes"]},
    "read_only": {"name": "Read-only", "grants": ["read", "events:changes"]},
    "everything": {"name": "Everything", "grants": sorted(
        {p.split(":", 1)[0] for p in PERMISSIONS - {PUBLIC}})},
    NO_ACCESS: {"name": "No access", "grants": []},
}


def is_grant(name: str) -> bool:
    return name in GRANTS or name.startswith(ADDON + ":")


def requires(permission: str) -> Dict[str, str]:
    """openapi_extra for a route that needs `permission`."""
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission {permission!r}")
    return {"x-permission": permission}


def allows(grants: FrozenSet[str], permission: str) -> bool:
    """A grant covers its own name and, for an area, every name in it."""
    return (permission == PUBLIC or permission in grants
            or permission.split(":", 1)[0] in grants)


@dataclass(frozen=True)
class Caller:
    """Who sent a request: an app, or one of the two "No key" rows."""
    name: str
    role: str
    role_name: str
    grants: FrozenSet[str]
    key: Optional[str]  # to resolve the same caller again (event streams)
    local: bool
    enabled: bool = True  # False: an app turned off in settings, granted nothing


# Set for each request by the auth middleware, and per action by the
# AnkiConnect dispatcher. Unset means no request: nothing is permitted.
current_caller: ContextVar[Optional[Caller]] = ContextVar("tsunagi_caller", default=None)


def permitted(permission: str) -> bool:
    """Whether the current request's caller has `permission`."""
    caller = current_caller.get()
    return caller is not None and allows(caller.grants, permission)


def current_denial(permission: str) -> str:
    """Why the current caller lacks `permission` (for handler-level checks)."""
    caller = current_caller.get()
    return denied_message(caller, permission) if caller else f"needs {permission}"


def denied_message(caller: Caller, permission: str) -> str:
    if not caller.enabled:
        return f"{caller.name} is turned off; turn it on under Apps & keys in Tsunagi's settings"
    return (f"{caller.name} has the role {caller.role_name!r}, which does not "
            f"allow {permission}; change it in Tsunagi's settings")
