"""
FSRS Helper (AnkiWeb 759844606) as an add-on action provider (backlog 2b-P,
R15). The add-on does not register itself, so this calls its modules
directly: only once Anki has loaded it (never importing it ourselves), and
only while each entry point has the parameters it was tested with. Anything
else makes the provider unsupported; nothing half-runs.

Tested with the AnkiWeb build whose `mod` is 1778741397 (May 2026), which
matches upstream main as of 2026-09-27.
"""
from __future__ import annotations

import datetime
import importlib
import inspect
import sys
import threading
from concurrent.futures import Future
from typing import Any, Callable, Dict, List, Optional

from ..addon_actions import ActionRefused, Registry

ADDON_ID = "759844606"
# module -> function -> parameter names, as tested
_ENTRY_POINTS = {
    "schedule.easy_days": {"easy_days": ["did"]},
    "schedule.reschedule": {"reschedule": [
        "did", "recent", "filter_flag", "filtered_cids", "easy_specific_due_dates",
        "apply_easy_days", "auto_reschedule"]},
    "schedule.schedule_break": {"_schedule_break_background": ["did", "break_days", "spread_days"]},
    "utils": {"sched_current_date": []},
}
_DECK = {"type": "integer", "description": "Deck id; all decks when omitted"}

# mw.reset() calls to wait for after the current action (see _watch). One
# job runs at a time, so one counter is enough.
_resets = 0


class _Unavailable(Exception):
    pass


def _mw() -> Any:
    from aqt import mw
    return mw


def _modules() -> Dict[str, Any]:
    mgr = _mw().addonManager
    if ADDON_ID not in mgr.allAddons():
        raise _Unavailable("FSRS Helper is not installed")
    if not mgr.addon_meta(ADDON_ID).enabled:
        raise _Unavailable("FSRS Helper is disabled")
    if ADDON_ID not in sys.modules:
        raise _Unavailable("FSRS Helper did not load; restart Anki")
    mods = {}
    for name, functions in _ENTRY_POINTS.items():
        try:  # already loaded by the add-on's own __init__
            mods[name] = importlib.import_module(f"{ADDON_ID}.{name}")
        except Exception as exc:
            raise _Unavailable(f"FSRS Helper's {name} could not be loaded ({exc})") from None
        for fn, params in functions.items():
            found = getattr(mods[name], fn, None)
            if not callable(found) or list(inspect.signature(found).parameters) != params:
                raise _Unavailable(
                    f"this version of FSRS Helper is not supported ({name}.{fn} changed)")
    return mods


def _available() -> Optional[str]:
    try:
        _modules()
    except _Unavailable as exc:
        return str(exc)
    return None


def _watch() -> Callable[[float], bool]:
    """Count mw.reset() calls from before the action: each entry point ends
    with one, plus one for the add-on's chained disperse when its
    auto_disperse_after_reschedule is on (verified, 2b-P)."""
    global _resets
    from aqt import gui_hooks
    mw = _mw()
    _resets = 0
    cond = threading.Condition()
    seen = [0]

    def on_reset() -> None:
        with cond:
            seen[0] += 1
            cond.notify_all()

    gui_hooks.state_did_reset.append(on_reset)

    def wait(timeout: float) -> bool:
        try:
            with cond:
                return cond.wait_for(lambda: seen[0] >= _resets, timeout)
        finally:
            mw.taskman.run_on_main(lambda: gui_hooks.state_did_reset.remove(on_reset))
    return wait


def _config() -> Dict[str, Any]:
    return _mw().addonManager.getConfig(ADDON_ID) or {}


def _expect_resets() -> None:
    global _resets
    _resets = 2 if _config().get("auto_disperse_after_reschedule") else 1


def _require_fsrs(deck: Optional[int] = None) -> Dict[str, Any]:
    col = _mw().col
    if not col.get_config("fsrs"):
        raise ActionRefused("FSRS is off; turn it on in Anki's deck options")
    if deck is not None and not col.decks.get(deck, default=False):
        raise ActionRefused(f"Deck {deck} does not exist")
    return _modules()


def _counted(result: Any) -> Dict[str, Any]:
    # (count, text), or (count, text, note ids) with auto-disperse on
    if not result:
        raise ActionRefused("FSRS Helper did nothing (is FSRS on?)")
    return {"cards": result[0], "message": result[1]}


def _then(fut: Optional[Future], fn: Callable[[Any], Any]) -> Future:
    if fut is None:
        raise ActionRefused("FSRS Helper did nothing (is FSRS on?)")
    out: Future = Future()

    def done(f: Future) -> None:
        try:
            out.set_result(fn(f.result()))
        except BaseException as exc:
            out.set_exception(exc)
    fut.add_done_callback(done)
    return out


# ---- actions (main thread) ----

def easy_dates() -> List[str]:
    return sorted(_config().get("easy_dates") or [])


def easy_days() -> Dict[str, Any]:
    mods = _require_fsrs()
    _expect_resets()
    # Blocks the main thread until done, as from the menu (R15).
    return _counted(mods["schedule.easy_days"].easy_days(None))


def set_easy_dates(dates: List[str]) -> Any:
    mods = _require_fsrs()
    mw = _mw()
    today = mods["utils"].sched_current_date()
    keep = [d for d in dates if datetime.date.fromisoformat(d) >= today]
    config = _config()
    config["easy_dates"] = keep
    mw.addonManager.writeConfig(ADDON_ID, config)
    # As Anki's config editor does: the add-on keeps a copy loaded at startup
    # and reloads it only here. Without this, its window and menu toggles
    # would save the stale copy back and erase these dates.
    updated = mw.addonManager.configUpdatedAction(ADDON_ID)
    if updated:
        updated(config)
    if not keep:
        return {"cards": 0, "message": "", "easy_dates": []}
    # What the add-on's Apply button does (EasySpecificDateManagerWidget),
    # which returns nothing to wait on.
    dues = [mw.col.sched.today + (datetime.date.fromisoformat(d) - today).days for d in keep]
    cids = mw.col.db.list(f"""SELECT id FROM cards
        WHERE data != '' AND json_extract(data, '$.s') IS NOT NULL
        AND CASE WHEN odid==0 THEN due ELSE odue END IN ({','.join(map(str, dues))})""")
    undo = mw.col.add_custom_undo_entry("Easy Days")
    fut = mods["schedule.reschedule"].reschedule(
        None, recent=False, filter_flag=True, filtered_cids=set(cids),
        easy_specific_due_dates=dues, apply_easy_days=True)
    mw.col.merge_undo_entries(undo)
    _expect_resets()
    return _then(fut, lambda r: {**_counted(r), "easy_dates": keep})


def reschedule(recent: bool, deck: Optional[int] = None) -> Future:
    mods = _require_fsrs(deck)
    fut = mods["schedule.reschedule"].reschedule(deck, recent=recent)
    _expect_resets()
    return _then(fut, _counted)


def schedule_break(break_days: int, spread_days: int, deck: Optional[int] = None) -> Future:
    mods = _require_fsrs(deck)
    mw = _mw()
    out: Future = Future()

    # The add-on's on_done without its tooltips; the dialogs it asks first
    # are the parameters.
    def on_done(fut: Future) -> None:
        mw.progress.finish()
        try:
            result = fut.result()
        except BaseException as exc:
            out.set_exception(exc)
            return
        if result["count"]:
            mw.reset()
        out.set_result({"cards": result["count"], "skipped": result.get("skipped", 0),
                        "break_days": break_days, "spread_days": spread_days})

    mw.taskman.run_in_background(
        lambda: mods["schedule.schedule_break"]._schedule_break_background(
            deck, break_days, spread_days),
        on_done)
    return out  # resolves after its reset, so nothing to wait for


def provide(registry: Registry) -> None:
    registry.provide(
        "fsrs_helper", "FSRS Helper", addon=ADDON_ID, available=_available, watch=_watch,
        actions=[
            {"name": "easy_dates", "title": "Easy dates", "impact": "read", "run": easy_dates,
             "description": "The dates set in FSRS Helper's Easy Days for specific dates."},
            {"name": "easy_days", "title": "Apply easy days", "impact": "undoable", "run": easy_days,
             "shows_ui": True,
             "description": "Reschedule cards due in the next 35 days so fewer land on "
                            "easy days. Applies to all decks."},
            {"name": "set_easy_dates", "title": "Set easy dates", "impact": "undoable",
             "run": set_easy_dates, "shows_ui": True,
             "description": "Replace the easy dates, then reschedule the cards due on them, "
                            "like the add-on's Apply button. Past dates are dropped.",
             "params": {"dates": {"type": "dates", "required": True,
                                  "description": "Dates as YYYY-MM-DD; an empty list clears them"}}},
            {"name": "reschedule", "title": "Reschedule cards", "impact": "undoable",
             "run": reschedule, "shows_ui": True,
             "description": "Recompute due dates from FSRS for all cards or one deck, or only "
                            "for cards reviewed in the last days (the add-on's setting, 7 by "
                            "default).",
             "params": {"deck": _DECK,
                        "recent": {"type": "boolean", "default": False,
                                   "description": "Only recently reviewed cards"}}},
            {"name": "schedule_break", "title": "Schedule a break", "impact": "undoable",
             "run": schedule_break, "shows_ui": True,
             "description": "Move reviews due during a break to the days after it. The "
                            "add-on's confirmation dialog is not shown.",
             "params": {"break_days": {"type": "integer", "default": 3, "min": 1, "max": 60,
                                       "description": "Days off"},
                        "spread_days": {"type": "integer", "default": 7, "min": 1, "max": 180,
                                        "description": "Days after the break to spread the "
                                                       "reviews over"},
                        "deck": _DECK}},
        ])
