"""The bundled FSRS Helper provider (backlog 2b-P) against a stub package shaped
like the add-on (its modules, entry points and return values as R15 recorded).
The real add-on is checked by tools/check_fsrs_helper_provider.py."""
import datetime
import sys
import threading
import time
import types
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from test_v1_addons import HELPER, FakeAddonManager, populate

from tsunagi.adapters import addon_actions as actions
from tsunagi.adapters.addon_actions import ActionRefused
from tsunagi.adapters.jobs import jobs
from tsunagi.adapters.providers import fsrs_helper

BASE = "/v1/addons/fsrs_helper/actions"


class Manager(FakeAddonManager):
    def __init__(self, root):
        super().__init__(root)
        self.config = {"easy_dates": ["2026-12-25", "2026-10-01"],
                       "auto_disperse_after_reschedule": False}
        self.updated = []  # what the add-on's config-updated action received

    def getConfig(self, name):
        return dict(self.config) if name == HELPER else None

    def writeConfig(self, name, config):
        assert name == HELPER
        self.config = dict(config)

    def configUpdatedAction(self, name):
        return self.updated.append if name == HELPER else None


class Hook(list):
    def remove(self, fn):
        if fn in self:
            super().remove(fn)


class Stub:
    """The add-on's entry points. Resets fire on a timer, the way the add-on's
    on_done callbacks run on the main thread after the call returns."""

    def __init__(self, mw, manager):
        self.mw, self.manager, self.calls = mw, manager, []
        self.resets = None  # None: as the add-on does (1, or 2 with disperse)
        self.result = (20, "20 cards rescheduled")
        self.today = datetime.date(2026, 9, 27)

    def _later(self):
        n = self.resets
        if n is None:
            n = 2 if self.manager.config["auto_disperse_after_reschedule"] else 1
        threading.Timer(0.05, lambda: [self.mw.reset() for _ in range(n)]).start()

    def easy_days(self, did):
        self.calls.append(("easy_days", did))
        self._later()
        return self.result

    def reschedule(self, did, recent=False, filter_flag=False, filtered_cids=None,
                   easy_specific_due_dates=None, apply_easy_days=False, auto_reschedule=False):
        self.calls.append(("reschedule", did, recent, filter_flag, filtered_cids,
                           easy_specific_due_dates, apply_easy_days))
        self._later()
        fut = Future()
        fut.set_result(self.result)
        return fut

    def _schedule_break_background(self, did, break_days, spread_days):
        self.calls.append(("break", did, break_days, spread_days))
        return {"count": 5, "skipped": 1, "break_days": break_days, "spread_days": spread_days}

    def sched_current_date(self):
        return self.today

    def install(self, monkeypatch):
        modules = {"": {}, ".schedule": {}, ".utils": {"sched_current_date": self.sched_current_date},
                   ".schedule.easy_days": {"easy_days": self.easy_days},
                   ".schedule.reschedule": {"reschedule": self.reschedule},
                   ".schedule.schedule_break": {
                       "_schedule_break_background": self._schedule_break_background}}
        for suffix, attrs in modules.items():
            module = types.ModuleType(HELPER + suffix)
            for k, v in attrs.items():
                setattr(module, k, v)
            monkeypatch.setitem(sys.modules, HELPER + suffix, module)


@pytest.fixture()
def helper(tmp_path, monkeypatch, col, reset_settings):
    import aqt

    populate(tmp_path)
    manager = Manager(tmp_path)
    mw = aqt.mw
    hooks = SimpleNamespace(state_did_reset=Hook())
    monkeypatch.setattr(aqt, "gui_hooks", hooks, raising=False)
    monkeypatch.setattr(mw, "addonManager", manager, raising=False)
    monkeypatch.setattr(mw, "reset", lambda: [fn() for fn in list(hooks.state_did_reset)],
                        raising=False)
    monkeypatch.setattr(mw, "progress", SimpleNamespace(finish=lambda: None), raising=False)

    def run_in_background(task, on_done):
        fut = Future()
        try:
            fut.set_result(task())
        except Exception as exc:
            fut.set_exception(exc)
        on_done(fut)
        return fut

    monkeypatch.setattr(mw.taskman, "run_in_background", run_in_background, raising=False)
    monkeypatch.setattr(actions, "SETTLE_TIMEOUT", 2.0)
    col.set_config("fsrs", True)
    stub = Stub(mw, manager)
    stub.install(monkeypatch)
    stub.hooks = hooks
    reset_settings.update(addon_enabled={f"fsrs_helper/{n}": "undoable" for n in (
        "easy_days", "set_easy_dates", "reschedule", "schedule_break")})
    jobs.reset()
    yield stub
    jobs.reset()


def finished(job_id, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        snap = jobs.snapshot(job_id)
        if snap["status"] in ("done", "failed", "aborted"):
            return snap
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def run(client, name, body=None):
    resp = client.post(f"{BASE}/{name}:run", json=body)
    assert resp.status_code == 202, resp.text
    return finished(resp.json()["job_id"])


def test_listed_on_its_addon_and_offers_five_items(client, helper):
    assert client.get(f"/v1/addons/{HELPER}").json()["provider"] == "fsrs_helper"
    body = client.get(BASE).json()
    assert body["unsupported"] is None
    assert {i["name"]: i["impact"] for i in body["items"]} == {
        "easy_dates": "read", "easy_days": "undoable", "set_easy_dates": "undoable",
        "reschedule": "undoable", "schedule_break": "undoable"}
    assert all(i["shows_ui"] for i in body["items"] if i["impact"] != "read")


def test_easy_dates_are_read_from_its_config(client, helper):
    resp = client.post(f"{BASE}/easy_dates:run")
    assert resp.json()["result"] == ["2026-10-01", "2026-12-25"]


@pytest.mark.parametrize("disperse", [False, True])
def test_easy_days_waits_for_the_add_ons_resets(client, helper, disperse):
    helper.manager.config["auto_disperse_after_reschedule"] = disperse
    if disperse:
        helper.result = (20, "20 cards rescheduled", "(1,2)")
    snap = run(client, "easy_days")
    assert snap["status"] == "done", snap["error"]
    assert snap["result"]["result"] == {"cards": 20, "message": "20 cards rescheduled"}
    assert snap["result"]["settled"] is True
    assert helper.calls == [("easy_days", None)]
    assert list(helper.hooks.state_did_reset) == []  # watch removed its hook


def test_missing_chained_reset_is_reported_unsettled(client, helper):
    helper.manager.config["auto_disperse_after_reschedule"] = True
    helper.resets = 1  # the disperse never ends
    snap = run(client, "easy_days")
    assert snap["status"] == "done" and snap["result"]["settled"] is False


def test_fsrs_off_is_refused_before_calling_the_add_on(client, col, helper):
    col.set_config("fsrs", False)
    snap = run(client, "easy_days")
    assert snap["status"] == "failed" and snap["error"].startswith("FSRS is off")
    assert helper.calls == []


def test_set_easy_dates_writes_config_and_applies_them(client, col, helper):
    snap = run(client, "set_easy_dates", {"dates": ["2026-09-30", "2026-09-01", "2026-09-29"]})
    assert snap["status"] == "done", snap["error"]
    assert helper.manager.config["easy_dates"] == ["2026-09-29", "2026-09-30"]  # past dropped
    # The add-on is told, so its in-memory copy cannot save stale dates back.
    assert [c["easy_dates"] for c in helper.manager.updated] == [["2026-09-29", "2026-09-30"]]
    today = col.sched.today
    _, did, recent, filtered, cids, dues, apply = helper.calls[0]
    assert (did, recent, filtered, dues, apply) == (None, False, True, [today + 2, today + 3], True)
    assert snap["result"]["result"] == {"cards": 20, "message": "20 cards rescheduled",
                                        "easy_dates": ["2026-09-29", "2026-09-30"]}


def test_clearing_easy_dates_reschedules_nothing(client, helper):
    snap = run(client, "set_easy_dates", {"dates": []})
    assert snap["result"]["result"] == {"cards": 0, "message": "", "easy_dates": []}
    assert helper.manager.config["easy_dates"] == [] and helper.calls == []
    assert snap["result"]["settled"] is True


def test_reschedule_passes_deck_and_recent(client, col, helper):
    deck = col.decks.id("Japanese")
    snap = run(client, "reschedule", {"deck": deck, "recent": True})
    assert snap["status"] == "done", snap["error"]
    assert helper.calls[0][:3] == ("reschedule", deck, True)
    failed = run(client, "reschedule", {"deck": 999})
    assert (failed["status"], failed["error"]) == ("failed", "Deck 999 does not exist")


def test_schedule_break_runs_without_its_dialogs(client, helper):
    resets = []
    helper.hooks.state_did_reset.append(lambda: resets.append(1))
    snap = run(client, "schedule_break", {"break_days": 4})
    assert snap["status"] == "done", snap["error"]
    assert helper.calls == [("break", None, 4, 7)]
    assert snap["result"]["result"] == {"cards": 5, "skipped": 1, "break_days": 4, "spread_days": 7}
    assert resets == [1]


def test_unsupported_when_missing_disabled_unloaded_or_changed(helper, monkeypatch):
    assert fsrs_helper._available() is None
    monkeypatch.setattr(sys.modules[f"{HELPER}.schedule.easy_days"], "easy_days", lambda deck: None)
    assert "not supported (schedule.easy_days.easy_days changed)" in fsrs_helper._available()
    monkeypatch.delitem(sys.modules, HELPER)
    assert fsrs_helper._available() == "FSRS Helper did not load; restart Anki"
    meta = helper.manager.root / HELPER / "meta.json"
    meta.write_text('{"disabled": true}')
    assert fsrs_helper._available() == "FSRS Helper is disabled"
    monkeypatch.setattr(helper.manager, "allAddons", lambda: [])
    assert fsrs_helper._available() == "FSRS Helper is not installed"


def test_nothing_done_is_a_refusal():
    from tsunagi.adapters.providers.fsrs_helper import _counted, _then
    with pytest.raises(ActionRefused):
        _counted(None)
    with pytest.raises(ActionRefused):
        _then(None, _counted)
    assert _counted((3, "x", "(1)")) == {"cards": 3, "message": "x"}
