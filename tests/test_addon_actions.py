"""Add-on actions (backlog 2b-P): registry, permissions and the job contract,
against a fake provider."""
import time
from concurrent.futures import Future

import pytest
from access import key_required
from fastapi.routing import APIRoute

from tsunagi.adapters import addon_actions as actions
from tsunagi.adapters.addon_actions import ActionRefused, Item, Param, Registry
from tsunagi.adapters.jobs import jobs
from tsunagi.app import app

BASE = "/v1/addons/fake/actions"


class FakeAddon:
    """An add-on providing actions the way any add-on would, through provide()."""

    def __init__(self):
        self.reason = None
        self.calls = []
        self.settles = True
        self.waits = []
        self.relabel = None
        self.refuse = False

    def watch(self):
        self.calls.append("watch")

        def wait(timeout):
            self.waits.append(timeout)
            return self.settles and timeout > 0
        return wait

    def apply(self, days=3, deep=False):
        self.calls.append(("apply", days, deep))
        if self.refuse:
            raise ActionRefused("FSRS is off")
        return {"cards": days}

    def wipe(self):
        self.calls.append("wipe")
        return {"wiped": True}

    def provide(self, registry):
        def later():
            fut = Future()
            fut.set_result({"cards": 7})
            return fut

        actions.PROVIDERS.pop("fake", None)  # re-provide after a relabel
        registry.provide("fake", "Fake Helper", addon="1234",
                         available=lambda: self.reason, watch=self.watch, actions=[
            {"name": "dates", "title": "Easy dates", "level": "read",
             "run": lambda: ["2026-10-01"]},
            {"name": "apply", "title": "Apply", "level": self.relabel or "normal",
             "run": self.apply, "shows_ui": True,
             "params": {"days": {"type": "integer", "min": 1, "max": 60, "default": 3},
                        "deep": {"type": "boolean"}}},
            {"name": "later", "title": "Later", "level": "normal", "run": later},
            {"name": "wipe", "title": "Wipe", "level": "destructive", "run": self.wipe},
        ])


@pytest.fixture(autouse=True)
def clean_jobs():
    jobs.reset()
    yield
    jobs.reset()


@pytest.fixture()
def fake(monkeypatch):
    monkeypatch.setattr(actions, "PROVIDERS", {})
    addon = FakeAddon()
    addon.provide(Registry())
    return addon


def approve(settings, **levels):
    settings.update(addon_approvals={f"fake/{k}": v for k, v in levels.items()})


def finished(job_id, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        snap = jobs.snapshot(job_id)
        if snap["status"] in ("done", "failed", "aborted"):
            return snap
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def statuses(client, **kw):
    return {i["name"]: i["status"] for i in client.get(BASE, **kw).json()["items"]}


def run(client, name, body=None, **kw):
    return client.post(f"{BASE}/{name}:run", json=body, **kw)


def test_reads_are_allowed_and_actions_wait_for_approval(client, fake):
    body = client.get(BASE).json()
    assert body["title"] == "Fake Helper" and body["unsupported"] is None
    apply = next(i for i in body["items"] if i["name"] == "apply")
    assert apply["params"]["days"] == {"type": "integer", "description": "", "required": False,
                                       "default": 3, "min": 1, "max": 60}
    assert apply["shows_ui"] is True
    assert statuses(client) == {"dates": "allowed", "apply": "needs_approval",
                                "later": "needs_approval", "wipe": "needs_approval"}
    assert run(client, "dates").json()["result"] == ["2026-10-01"]
    resp = run(client, "apply")
    assert resp.status_code == 403 and "not approved" in resp.json()["detail"]
    assert fake.calls == []


def test_approved_normal_items_join_default_but_destructive_only_everything(client, fake, reset_settings):
    approve(reset_settings, apply="normal", wipe="destructive")
    assert statuses(client)["apply"] == "allowed"
    assert statuses(client)["wipe"] == "not_permitted"
    resp = run(client, "wipe")
    assert resp.status_code == 403 and "addon:fake/wipe" in resp.json()["detail"]
    reset_settings.update(no_key_local_role="everything")
    assert statuses(client)["wipe"] == "allowed"


def test_default_keeps_approved_items_as_its_defaults_until_edited(reset_settings):
    approve(reset_settings, apply="normal", wipe="destructive")
    assert "addon:fake/apply" in reset_settings.role("default")[1]
    assert "addon:fake/wipe" not in reset_settings.role("default")[1]
    reset_settings.update(roles={"default": {"name": "Default", "grants": ["read"]}})
    assert reset_settings.role("default")[1] == frozenset({"read"})
    reset_settings.update(roles={"mine": {"name": "Mine", "grants": ["addon:fake/wipe", "bogus"]}})
    assert reset_settings.role("mine")[1] == frozenset({"addon:fake/wipe"})


def test_a_relabelled_item_needs_approval_again(client, fake, reset_settings):
    approve(reset_settings, apply="normal")
    fake.relabel = "destructive"
    fake.provide(Registry())
    reset_settings.update(no_key_local_role="everything")
    assert statuses(client)["apply"] == "needs_approval"


def test_read_only_role_reads_but_cannot_run(client, fake, reset_settings):
    approve(reset_settings, apply="normal")
    reset_settings.update(**key_required("ro", role="read_only", name="Dashboard"))
    headers = {"X-Api-Key": "ro"}
    assert statuses(client, headers=headers)["apply"] == "not_permitted"
    assert run(client, "dates", headers=headers).status_code == 200
    resp = run(client, "apply", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"].startswith("Dashboard has the role 'Read-only'")
    assert client.get(BASE).status_code == 401  # keyless: No access


def test_action_runs_as_a_job_with_its_result(client, fake, reset_settings):
    approve(reset_settings, apply="normal")
    resp = run(client, "apply", {"days": 5, "deep": True})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert resp.headers["location"] == f"/v1/jobs/{job_id}"
    snap = finished(job_id)
    assert snap["kind"] == "addon:fake/apply" and snap["status"] == "done"
    assert snap["result"] == {"provider": "fake", "action": "apply", "result": {"cards": 5},
                              "settled": True, "backup": None}
    assert fake.calls == ["watch", ("apply", 5, True)]
    assert fake.waits == [actions.SETTLE_TIMEOUT]
    polled = client.get(f"/v1/jobs/{job_id}").json()
    assert polled["status"] == "done" and polled["progress"] is None


def test_defaults_fill_missing_params_and_futures_are_awaited(client, fake, reset_settings):
    approve(reset_settings, apply="normal", later="normal")
    assert finished(run(client, "apply").json()["job_id"])["result"]["result"] == {"cards": 3}
    assert finished(run(client, "later").json()["job_id"])["result"]["result"] == {"cards": 7}


def test_unsettled_follow_up_work_is_reported(client, fake, reset_settings):
    approve(reset_settings, apply="normal")
    fake.settles = False
    snap = finished(run(client, "apply").json()["job_id"])
    assert snap["status"] == "done" and snap["result"]["settled"] is False


def test_refusal_fails_the_job_and_releases_the_watch(client, fake, reset_settings):
    approve(reset_settings, apply="normal")
    fake.refuse = True
    snap = finished(run(client, "apply").json()["job_id"])
    assert (snap["status"], snap["error"]) == ("failed", "FSRS is off")
    assert fake.waits == [0]


@pytest.mark.parametrize("body, message", [
    ({"nope": 1}, "Unknown parameter(s) for apply: nope"),
    ({"days": 0}, "days must be between 1 and 60"),
    ({"days": True}, "days must be an integer"),
    ({"deep": "yes"}, "deep must be true or false"),
])
def test_bad_params_are_refused_before_anything_runs(client, fake, reset_settings, body, message):
    approve(reset_settings, apply="normal")
    resp = run(client, "apply", body)
    assert resp.status_code == 400 and resp.json()["detail"] == message
    assert fake.calls == []


def test_dates_param_is_checked_and_normalised():
    item = Item("x", "X", "", "normal", lambda dates: None,
                params={"dates": Param("dates", required=True)})
    assert actions.validate(item, {"dates": ["2026-10-02", "2026-10-01", "2026-10-02"]}) == {
        "dates": ["2026-10-01", "2026-10-02"]}
    with pytest.raises(actions.ValidationError, match="is not a date"):
        actions.validate(item, {"dates": ["2026-13-01"]})
    with pytest.raises(actions.ValidationError, match="dates is required"):
        actions.validate(item, {})


def test_unsupported_provider_lists_why_and_refuses_to_run(client, fake, reset_settings):
    approve(reset_settings, apply="normal")
    fake.reason = "FSRS Helper is not installed"
    body = client.get(BASE).json()
    assert body["unsupported"] == "FSRS Helper is not installed" and body["items"] == []
    resp = run(client, "apply")
    assert resp.status_code == 409 and "not installed" in resp.json()["detail"]


def test_unknown_provider_or_action_is_404(client, fake):
    assert client.get("/v1/addons/nope/actions").status_code == 404
    assert run(client, "nope").status_code == 404


def test_busy_job_slot_is_409_and_actions_cannot_be_aborted(client, fake, reset_settings):
    approve(reset_settings, apply="normal")
    busy = jobs.create("compute_params")
    assert run(client, "apply").status_code == 409
    jobs.fail(busy.id, "done with it")
    job_id = run(client, "apply").json()["job_id"]
    finished(job_id)
    job = jobs.create("addon:fake/apply")
    resp = client.post(f"/v1/jobs/{job.id}:abort")
    assert resp.status_code == 409 and "cannot be aborted" in resp.json()["detail"]


def test_destructive_action_makes_a_backup_first(client, col, fake, reset_settings, tmp_path, monkeypatch):
    import aqt
    folder = tmp_path / "backups"
    folder.mkdir()
    monkeypatch.setattr(aqt.mw.pm, "backupFolder", lambda: str(folder), raising=False)
    approve(reset_settings, wipe="destructive")
    reset_settings.update(no_key_local_role="everything")
    snap = finished(run(client, "wipe").json()["job_id"], seconds=30)
    assert snap["status"] == "done", snap["error"]
    backups = list(folder.glob("*.colpkg"))
    assert len(backups) == 1 and snap["result"]["backup"] == {"path": str(backups[0])}
    assert fake.calls == ["watch", "wipe"]


def test_no_backup_means_the_destructive_action_does_not_run(client, col, fake, reset_settings,
                                                             tmp_path, monkeypatch):
    import aqt
    monkeypatch.setattr(aqt.mw.pm, "backupFolder", lambda: str(tmp_path / "missing"), raising=False)
    monkeypatch.setattr(actions, "query_op_call", lambda *a, **k: False)
    approve(reset_settings, wipe="destructive")
    reset_settings.update(no_key_local_role="everything")
    snap = finished(run(client, "wipe").json()["job_id"])
    assert snap["status"] == "failed" and "no backup" in snap["error"]
    assert fake.calls == []


def test_addon_listing_names_its_provider(fake):
    assert actions.provider_for_addon("1234") == "fake"
    assert actions.provider_for_addon("5678") is None


def test_duplicate_provider_ids_are_refused(fake):
    with pytest.raises(ValueError, match="'fake' is already used by add-on 1234"):
        Registry().provide("fake", "Other", [])


def test_only_the_run_route_defers_its_permission_to_the_handler():
    deferred = [route.path for route in app.routes if isinstance(route, APIRoute)
                and (route.openapi_extra or {}).get("x-permission") == actions.ADDON]
    assert deferred == ["/v1/addons/{provider_id}/actions/{name}:run"]


def test_capabilities_report_each_provider_and_leave_items_to_the_list(client, fake):
    report = client.get("/v1/capabilities").json()
    assert report["features"]["addon_actions.fake"]["status"] == "available"
    run_op = report["operations"]["POST /v1/addons/{provider_id}/actions/{name}:run"]
    assert run_op["status"] == "available"  # per item: GET .../actions
    fake.reason = "FSRS Helper is disabled"
    feature = client.get("/v1/capabilities").json()["features"]["addon_actions.fake"]
    assert (feature["status"], feature["reason"]) == ("unsupported", "FSRS Helper is disabled")


def test_a_provider_check_that_raises_reads_as_unsupported(client, fake, monkeypatch):
    import dataclasses
    broken = dataclasses.replace(actions.PROVIDERS["fake"], available=lambda: 1 / 0)
    monkeypatch.setitem(actions.PROVIDERS, "fake", broken)
    assert actions.unavailable(broken) == "Fake Helper could not be checked (division by zero)"
    assert client.get(BASE).json()["unsupported"].startswith("Fake Helper could not be checked")


def run_it():
    return None


@pytest.mark.parametrize("args, message", [
    (("Bad-Id", "X", []), "may only use a-z"),
    (("x", "X", [{"name": "a", "level": "huge", "run": run_it}]), "level must be one of"),
    (("x", "X", [{"name": "a", "level": "normal", "run": 5}]), "run must be callable"),
    (("x", "X", [{"name": "a", "level": "normal", "run": run_it,
                  "params": {"p": {"type": "float"}}}]), "type must be one of"),
    (("x", "X", [{"name": "a", "level": "normal", "run": run_it,
                  "params": {"p": {"type": "string", "colour": "red"}}}]), "a.p:"),
    (("x", "X", [{"name": "a", "level": "read", "run": run_it},
                 {"name": "a", "level": "read", "run": run_it}]), "same name"),
])
def test_provide_refuses_a_bad_shape(monkeypatch, args, message):
    monkeypatch.setattr(actions, "PROVIDERS", {})
    with pytest.raises(ValueError, match=message):
        Registry().provide(*args)
    assert actions.PROVIDERS == {}


def test_the_owning_add_on_is_where_run_is_defined(monkeypatch):
    monkeypatch.setattr(actions, "PROVIDERS", {})
    Registry().provide("mine", "Mine", [{"name": "a", "level": "read", "run": run_it}])
    assert actions.PROVIDERS["mine"].addon_id == __name__.split(".")[0]


def test_string_params_are_checked():
    item = Item("x", "X", "", "normal", run_it, params={"q": Param("string")})
    assert actions.validate(item, {"q": "deck:Japanese"}) == {"q": "deck:Japanese"}
    with pytest.raises(actions.ValidationError, match="q must be a string"):
        actions.validate(item, {"q": 3})


def test_collect_calls_every_add_on_and_isolates_a_broken_one(monkeypatch):
    from anki import hooks
    monkeypatch.setitem(hooks._hooks, actions.HOOK, [])
    monkeypatch.setattr(actions, "PROVIDERS", {})
    Registry(bundled=True).provide("ours", "Ours", [{"name": "a", "level": "read", "run": run_it}])

    def good(registry):
        assert registry.version == actions.API_VERSION
        registry.provide("good", "Good", [{"name": "a", "level": "read", "run": run_it}])

    def broken(registry):
        raise RuntimeError("oops")

    def late(registry):
        registry.provide("late", "Late", [{"name": "a", "level": "read", "run": run_it}])

    for fn in (good, broken, late):
        hooks.addHook(actions.HOOK, fn)
    assert actions.collect() == ["oops"]
    assert sorted(actions.PROVIDERS) == ["good", "late", "ours"]
    assert broken not in hooks._hooks[actions.HOOK]  # Anki's runHook dropped it
    # Collecting again (a server restart) replaces add-ons' providers, not ours.
    assert actions.collect() == []
    assert sorted(actions.PROVIDERS) == ["good", "late", "ours"]
