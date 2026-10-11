"""
Access requests (6.124): a website or a program asks for access, Anki asks you,
and if you allow it, it becomes an app in Apps & keys with the role you chose
and gets its key, once, in the answer.

A website is told apart by its origin, which only a browser can't fake; a
program by the name it gives, which can't be checked, so the prompt says so.
Asking again always prompts (anything that can claim a site's origin could
otherwise collect its key), and allowing gives the requester's app a new key.
One prompt per requester at a time: requests that arrive meanwhile get its answer.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from ..shared.permissions import BUILTIN_ROLES, NO_ACCESS

TIMEOUT = 130.0  # a little over the prompt's own two minutes


@dataclass(frozen=True)
class AccessAsk:
    """What the prompt shows."""
    origin: Optional[str]              # a website; None for a program
    name: str                          # the app's name if allowed
    address: Optional[str]             # another device's address; None on this computer
    existing: Optional[Tuple[str, str, bool]]  # (app name, role name, on) if it has an app already
    roles: List[Tuple[str, str]]       # (id, name), every role but No access
    role: str                          # preselected role id


@dataclass
class AccessDecision:
    accepted: bool = False
    role: Optional[str] = None
    ignore: bool = False

    def __bool__(self) -> bool:
        return self.accepted


@dataclass
class _Pending:
    done: threading.Event = field(default_factory=threading.Event)
    answer: Dict[str, Any] = field(default_factory=lambda: {"permission": "denied"})


_lock = threading.Lock()
_pending: Dict[str, _Pending] = {}


def _roles(settings: Any) -> List[Tuple[str, str]]:
    ids = list(BUILTIN_ROLES) + [r for r in (settings.get("roles") or {}) if r not in BUILTIN_ROLES]
    return [(rid, settings.role(rid)[0]) for rid in ids if rid != NO_ACCESS]


def _suggested_role(roles: List[Tuple[str, str]], wanted: Optional[str]) -> str:
    """A role the request suggests, by id or name; Default otherwise."""
    if wanted:
        for rid, name in roles:
            if wanted in (rid, name) or wanted.casefold() == name.casefold():
                return rid
    return "default"


def _app_name(origin: Optional[str], name: Optional[str], address: Optional[str]) -> str:
    if name and name.strip():
        return name.strip()
    if origin:
        return urlsplit(origin).netloc or origin
    return f"Program on {address}" if address else "Program on this computer"


def _existing(apps: List[Dict[str, Any]], origin: Optional[str], name: str) -> Optional[int]:
    """The requester's app: by origin for a website, by name for a program."""
    for i, app in enumerate(apps):
        if origin and app.get("origin") == origin:
            return i
        if not origin and not app.get("origin") and app.get("name") == name:
            return i
    return None


def _free_name(apps: List[Dict[str, Any]], name: str, skip: Optional[int]) -> str:
    taken = {a.get("name") for i, a in enumerate(apps) if i != skip}
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name} ({n})", n + 1
    return candidate


def request_access(settings: Any, ask: Callable[[AccessAsk], AccessDecision], *,
                   origin: Optional[str], local: bool, address: Optional[str],
                   name: Optional[str] = None, role: Optional[str] = None) -> Dict[str, Any]:
    """The answer for POST /v1/permissions:request: {permission} or, allowed,
    {permission, key, app, role}."""
    if settings.is_blocked_anki_page(origin):
        return {"permission": "denied"}  # a card template can't talk you into it
    if origin:
        if origin in (settings.get("ankiconnect_ignore_origins") or []):
            return {"permission": "denied"}
    app_name = _app_name(origin, name, None if local else address)
    if not origin and app_name in (settings.get("ignored_programs") or []):
        return {"permission": "denied"}

    requester = origin or f"program:{app_name}"
    with _lock:
        pending = _pending.get(requester)
        first = pending is None
        if first:
            pending = _pending[requester] = _Pending()
    if not first:
        pending.done.wait(TIMEOUT)
        return dict(pending.answer)
    try:
        pending.answer = _ask_and_apply(settings, ask, origin, local, address, app_name, role)
        return dict(pending.answer)
    finally:
        pending.done.set()
        with _lock:
            _pending.pop(requester, None)


def _ask_and_apply(settings: Any, ask: Callable[[AccessAsk], AccessDecision], origin: Optional[str],
                   local: bool, address: Optional[str], app_name: str, role: Optional[str]) -> Dict[str, Any]:
    apps = [dict(a) for a in settings.get("apps") or [] if isinstance(a, dict)]
    roles = _roles(settings)
    found = _existing(apps, origin, app_name)
    existing = None
    if found is not None:
        existing = (str(apps[found].get("name")), settings.role(apps[found].get("role"))[0],
                    apps[found].get("enabled") is not False)
    decision = ask(AccessAsk(origin=origin, name=app_name, address=None if local else address,
                             existing=existing, roles=roles, role=_suggested_role(roles, role)))
    if not decision:
        if decision.ignore:
            if origin:
                settings.update(ankiconnect_ignore_origins=[
                    *settings.get("ankiconnect_ignore_origins", []), origin])
            else:
                settings.update(ignored_programs=[*settings.get("ignored_programs", []), app_name])
        return {"permission": "denied"}

    chosen = decision.role if decision.role in {rid for rid, _ in roles} else "default"
    key = secrets.token_urlsafe(24)
    # Read again: the prompt waited, and settings may have been saved meanwhile.
    apps = [dict(a) for a in settings.get("apps") or [] if isinstance(a, dict)]
    found = _existing(apps, origin, app_name)
    if found is None:
        app = {"name": _free_name(apps, app_name, None), "key": key, "role": chosen}
        if origin:
            app["origin"] = origin
        apps.append(app)
    else:
        app = apps[found]
        app.update(key=key, role=chosen)
        app.pop("enabled", None)  # allowing again turns it back on
    settings.update(apps=apps)
    return {"permission": "granted", "key": key, "app": app["name"], "role": settings.role(chosen)[0]}
