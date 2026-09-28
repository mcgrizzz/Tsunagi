"""
Add-on actions (backlog 2b, design in docs/backlog.md 2b-P): what an add-on's
buttons and screens do, offered through providers. Reads return data; other
actions run as jobs.

Any add-on can be a provider without importing Tsunagi (its folder name
differs between installs, and it may load later). It adds a legacy hook, and
Tsunagi calls it with a Registry once every add-on has loaded:

    from anki.hooks import addHook
    addHook("tsunagi.register", lambda registry: registry.provide(...))

The contract is plain dicts and callables, documented for add-on authors in
docs/addon_providers.md. Tsunagi's own providers (adapters/providers/) use
the same `provide`.

Permissions: a read needs read:addons. Any other item needs the user's
approval at its current level (config `addon_enabled`) and a grant of
`addon:<provider>/<item>` or the whole `addon` area.
"""
from __future__ import annotations

import datetime
import logging
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..shared.errors import ResourceNotFoundError, ValidationError, anki_error_detail
from ..shared.permissions import ADDON, Caller, allows
from .anki.collection import redraw_main_screen
from .jobs import jobs
from .ops import FOREVER, call_on_main, query_op_call
from .settings import settings

HOOK = "tsunagi.register"
API_VERSION = 1
LEVELS = ("read", "normal", "destructive")
PARAM_TYPES = ("integer", "boolean", "string", "dates")
SETTLE_TIMEOUT = 120.0  # seconds to wait for an add-on's follow-up work
_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")

log = logging.getLogger(__name__)


class ActionRefused(Exception):
    """The add-on would not run the item (e.g. FSRS is off); the job fails with this.
    External providers raise any exception; its message becomes the job's error."""


@dataclass(frozen=True)
class Param:
    type: str
    description: str = ""
    required: bool = False
    default: Any = None
    min: Optional[int] = None
    max: Optional[int] = None


@dataclass(frozen=True)
class Item:
    name: str
    title: str
    description: str
    level: str
    run: Callable[..., Any]  # main thread, validated params as keywords
    params: Dict[str, Param] = field(default_factory=dict)
    shows_ui: bool = False  # progress window or tooltip on the PC


@dataclass(frozen=True)
class Provider:
    id: str
    title: str
    items: List[Item]
    addon_id: Optional[str]  # folder name of the add-on it offers
    # None, or why it cannot run now (missing, disabled, incompatible).
    available: Optional[Callable[[], Optional[str]]] = None
    # Called on the main thread just before an action runs. May return a
    # function the worker calls afterwards with a timeout: True once the
    # add-on's follow-up work has ended, False on timeout. Also called with 0
    # when the action fails, to clean up.
    watch: Optional[Callable[[], Optional[Callable[[float], bool]]]] = None
    bundled: bool = False


PROVIDERS: Dict[str, Provider] = {}


class Registry:
    """What `tsunagi.register` callbacks receive."""
    version = API_VERSION

    def __init__(self, bundled: bool = False) -> None:
        self._bundled = bundled

    def provide(self, id: str, title: str, actions: List[Dict[str, Any]], *,
                available: Optional[Callable[[], Optional[str]]] = None,
                watch: Optional[Callable[[], Any]] = None,
                addon: Optional[str] = None) -> None:
        """Offer `actions` under `id` (a-z, 0-9, _; the same on every install).
        `addon` is the add-on folder they belong to, by default the one
        defining the first action's `run`. Raises ValueError on a bad shape or
        an id already used."""
        if not isinstance(id, str) or not id or not set(id) <= _ID_CHARS:
            raise ValueError(f"provider id {id!r} may only use a-z, 0-9 and _")
        if id in PROVIDERS:
            raise ValueError(f"provider id {id!r} is already used by add-on "
                             f"{PROVIDERS[id].addon_id}")
        items = [_item(a) for a in actions]
        names = [i.name for i in items]
        if len(set(names)) != len(names):
            raise ValueError(f"{id}: two actions have the same name")
        if addon is None and items:
            addon = getattr(items[0].run, "__module__", "").split(".")[0] or None
        PROVIDERS[id] = Provider(id, str(title), items, addon, available, watch, self._bundled)


def _item(spec: Dict[str, Any]) -> Item:
    name = spec.get("name")
    if not isinstance(name, str) or not name or not set(name) <= _ID_CHARS:
        raise ValueError(f"action name {name!r} may only use a-z, 0-9 and _")
    if spec.get("level") not in LEVELS:
        raise ValueError(f"{name}: level must be one of {', '.join(LEVELS)}")
    if not callable(spec.get("run")):
        raise ValueError(f"{name}: run must be callable")
    params = {}
    for pname, p in (spec.get("params") or {}).items():
        if p.get("type") not in PARAM_TYPES:
            raise ValueError(f"{name}.{pname}: type must be one of {', '.join(PARAM_TYPES)}")
        try:
            params[pname] = Param(**p)
        except TypeError as exc:
            raise ValueError(f"{name}.{pname}: {exc}") from None
    return Item(name, str(spec.get("title") or name), str(spec.get("description") or ""),
                spec["level"], spec["run"], params, bool(spec.get("shows_ui")))


def collect() -> List[str]:
    """
    (Re)collect add-on providers: call every `tsunagi.register` callback on
    the main thread. Called from start_server on profile_did_open, which Anki
    fires only after AddonManager.loadAddons() has imported every add-on
    (AnkiQt.__init__ loads add-ons, then schedules the profile load). Anki's runHook drops a
    callback that raises and stops there, so run it again until a pass
    completes; each failure removes one callback. Returns the failures.
    """
    from anki.hooks import runHook
    failures = []
    while True:
        for pid in [p.id for p in PROVIDERS.values() if not p.bundled]:
            del PROVIDERS[pid]
        try:
            runHook(HOOK, Registry())
            return failures
        except Exception as exc:
            failures.append(str(exc))
            log.warning("An add-on failed to register Tsunagi actions: %s", exc)


def unavailable(provider: Provider) -> Optional[str]:
    """provider.available() on the main thread, failing closed: an error in
    the check reads as unsupported rather than breaking the caller."""
    if provider.available is None:
        return None

    def check() -> Optional[str]:
        try:
            return provider.available()
        except Exception as exc:
            return f"{provider.title} could not be checked ({exc})"
    return call_on_main(check)


def provider_for_addon(addon_id: str) -> Optional[str]:
    return next((p.id for p in PROVIDERS.values() if p.addon_id == addon_id), None)


def find(provider_id: str, name: Optional[str] = None):
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ResourceNotFoundError("Add-on provider", provider_id)
    if name is None:
        return provider, None
    item = next((i for i in provider.items if i.name == name), None)
    if item is None:
        raise ResourceNotFoundError("Add-on action", f"{provider_id}/{name}")
    return provider, item


def status(caller: Caller, provider: Provider, item: Item) -> str:
    """allowed, disabled or not_permitted (unsupported is per provider)."""
    if item.level == "read":
        return "allowed" if allows(caller.grants, "read:addons") else "not_permitted"
    key = f"{provider.id}/{item.name}"
    if settings.addon_enabled().get(key) != item.level:
        return "disabled"  # never enabled, or relabelled since
    return "allowed" if allows(caller.grants, f"{ADDON}:{key}") else "not_permitted"


def validate(item: Item, body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    body = dict(body or {})
    unknown = sorted(set(body) - set(item.params))
    if unknown:
        raise ValidationError(f"Unknown parameter(s) for {item.name}: {', '.join(unknown)}")
    out = {}
    for name, param in item.params.items():
        if name not in body or body[name] is None:
            if param.required:
                raise ValidationError(f"{name} is required")
            if param.default is not None:
                out[name] = param.default
            continue
        out[name] = _check(name, param, body[name])
    return out


def _check(name: str, param: Param, value: Any) -> Any:
    if param.type == "boolean":
        if not isinstance(value, bool):
            raise ValidationError(f"{name} must be true or false")
        return value
    if param.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(f"{name} must be an integer")
        if (param.min is not None and value < param.min) or (param.max is not None and value > param.max):
            raise ValidationError(f"{name} must be between {param.min} and {param.max}")
        return value
    if param.type == "string":
        if not isinstance(value, str):
            raise ValidationError(f"{name} must be a string")
        return value
    if param.type == "dates":
        if not isinstance(value, list):
            raise ValidationError(f"{name} must be a list of dates (YYYY-MM-DD)")
        for day in value:
            try:
                datetime.date.fromisoformat(day)
            except (TypeError, ValueError):
                raise ValidationError(f"{name}: {day!r} is not a date (YYYY-MM-DD)") from None
        return sorted(set(value))
    raise ValueError(f"Unknown parameter type {param.type!r}")


def read(item: Item, params: Dict[str, Any]) -> Any:
    return call_on_main(item.run, **params)


def submit(provider: Provider, item: Item, params: Dict[str, Any]) -> str:
    """Start an action as a job; returns the job id. The single job slot is
    shared with FSRS computations and imports (409 when busy)."""
    job = jobs.create(f"{ADDON}:{provider.id}/{item.name}")
    threading.Thread(target=_work, args=(job.id, provider, item, params),
                     name=f"tsunagi-{job.kind}", daemon=True).start()
    return job.id


def _work(job_id: str, provider: Provider, item: Item, params: Dict[str, Any]) -> None:
    jobs.mark_running(job_id)
    waiter = None
    ran = False
    try:
        backup = _backup() if item.level == "destructive" else None

        def start():
            nonlocal waiter, ran
            waiter = provider.watch() if provider.watch else None
            ran = True
            return item.run(**params)

        value = call_on_main(start, timeout=FOREVER)
        if isinstance(value, Future):
            value = value.result()
        settled = waiter(SETTLE_TIMEOUT) if waiter else True
        waiter = None
        _redraw()
        jobs.finish(job_id, {"provider": provider.id, "action": item.name, "result": value,
                             "settled": settled, "backup": backup})
    except ActionRefused as exc:
        if ran:
            _redraw()
        jobs.fail(job_id, str(exc))
    except Exception as exc:
        if ran:
            _redraw()
        jobs.fail(job_id, anki_error_detail(exc))
    finally:
        if waiter:
            waiter(0)


def _redraw() -> None:
    """Show the add-on's changes now, not a dimmed page until Anki is focused
    (redraw_main_screen); a failure here never fails the job."""
    from aqt import mw
    try:
        call_on_main(redraw_main_screen, mw)
    except Exception:
        log.exception("Could not redraw Anki's main screen after an add-on action")


def _backup() -> Dict[str, str]:
    """Anki backup before a destructive item; the action does not run without one.
    The backend names no file, so report the newest one (also right when the
    backend skipped the backup because nothing changed since the last)."""
    from aqt import mw
    folder = mw.pm.backupFolder()
    query_op_call(lambda col: col.create_backup(backup_folder=folder, force=True,
                                                wait_for_completion=True), timeout=FOREVER)
    backups = sorted(Path(folder).glob("*.colpkg"), key=lambda p: p.stat().st_mtime)
    if not backups:
        raise RuntimeError("Anki made no backup, so the action did not run")
    return {"path": str(backups[-1])}
