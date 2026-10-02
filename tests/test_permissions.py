"""Permissions: every route and action declares one, and roles enforce them (6.5a)."""

import pytest
from access import key_required
from fastapi.routing import APIRoute

from tsunagi.app import app
from tsunagi.http.compat.registry import AnkiConnectRegistry, registry
from tsunagi.shared.permissions import BUILTIN_ROLES, PERMISSIONS, allows, requires


def test_every_route_declares_a_known_permission():
    missing = [
        f"{sorted(route.methods)} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        and (route.openapi_extra or {}).get("x-permission") not in PERMISSIONS
    ]
    assert not missing


def test_every_compat_action_declares_a_known_permission():
    undeclared = [a for a in registry.list_actions()
                  if registry.permission_of(a) not in PERMISSIONS]
    assert registry.list_actions() and not undeclared


def test_default_role_allows_every_ankiconnect_action():
    # Swapping Tsunagi in for AnkiConnect must just work.
    grants = frozenset(BUILTIN_ROLES["default"]["grants"])
    assert [a for a in registry.list_actions()
            if not allows(grants, registry.permission_of(a))] == []


def test_unknown_permission_is_rejected():
    with pytest.raises(ValueError):
        requires("write:everything")
    with pytest.raises(ValueError):
        AnkiConnectRegistry().register("x", permission="write:everything")


def test_an_area_grant_covers_its_names_but_a_name_does_not_cover_the_area():
    assert allows(frozenset({"write"}), "write:notes")
    assert allows(frozenset({"write"}), "write")
    assert not allows(frozenset({"write:notes"}), "write")  # undo needs all of write
    assert not allows(frozenset({"write:notes"}), "write:cards")


@pytest.fixture()
def read_only(reset_settings):
    reset_settings.update(**key_required("ro", role="read_only", name="Dashboard"))
    return {"X-Api-Key": "ro"}


def test_read_only_app_reads_but_cannot_write_through_v1(client, col, read_only):
    assert client.get("/v1/decks", headers=read_only).status_code == 200
    resp = client.post("/v1/decks", json={"name": "Nope"}, headers=read_only)
    assert resp.status_code == 403
    assert resp.json()["detail"] == (
        "Dashboard has the role 'Read-only', which does not allow write:decks; "
        "change it in Tsunagi's settings")
    assert "Nope" not in [d.name for d in col.decks.all_names_and_ids()]


def test_read_only_app_reads_but_cannot_write_through_ankiconnect(client, col, read_only):
    names = client.post("/", json={"action": "deckNames", "version": 6, "key": "ro"}).json()
    assert names == {"result": ["Default"], "error": None}
    denied = client.post("/", json={"action": "createDeck", "version": 6, "key": "ro",
                                    "params": {"deck": "Nope"}}).json()
    assert denied["result"] is None and "does not allow write:decks" in denied["error"]
    assert "Nope" not in [d.name for d in col.decks.all_names_and_ids()]


def test_an_app_turned_off_is_refused_and_does_not_fall_back_to_no_key(client, col, reset_settings):
    # This computer's No key row stays Default, so falling back would let it in.
    reset_settings.update(apps=[{"name": "Yomitan", "key": "yk", "role": "default", "enabled": False}])
    resp = client.get("/v1/decks", headers={"X-Api-Key": "yk"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == (
        "Yomitan is turned off; turn it on under Apps & keys in Tsunagi's settings")
    denied = client.post("/", json={"action": "deckNames", "version": 6, "key": "yk"}).json()
    assert denied["result"] is None and "Yomitan is turned off" in denied["error"]
    assert client.get("/v1/decks").status_code == 200  # keyless callers are unaffected


def test_undo_needs_all_of_write(client, reset_settings):
    reset_settings.update(roles={"notes": {"name": "Notes", "grants": ["write:notes", "gui"]}},
                          no_key_local_role="notes")
    resp = client.post("/v1/gui:undo")
    assert resp.status_code == 403 and "does not allow write" in resp.json()["detail"]


def test_capabilities_show_the_calling_apps_permissions(client, read_only):
    ops = client.get("/v1/capabilities", headers=read_only).json()["operations"]
    assert ops["GET /v1/decks"]["status"] == "available"
    assert ops["POST /v1/decks"]["status"] == "disabled"
    assert ops["POST /v1/decks"]["setting"] == "permissions.write:decks"
