"""Every route and AnkiConnect action declares a known permission (6.5a)."""

import pytest
from fastapi.routing import APIRoute

from tsunagi.app import app
from tsunagi.http.compat.registry import AnkiConnectRegistry, registry
from tsunagi.shared.permissions import PERMISSIONS, requires


def test_every_route_declares_a_known_permission():
    # Routes hidden from the schema are the docs pages, which stay public.
    missing = [
        f"{sorted(route.methods)} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute) and route.include_in_schema
        and (route.openapi_extra or {}).get("x-permission") not in PERMISSIONS
    ]
    assert not missing


def test_every_compat_action_declares_a_known_permission():
    undeclared = [a for a in registry.list_actions()
                  if registry.permission_of(a) not in PERMISSIONS]
    assert registry.list_actions() and not undeclared


def test_unknown_permission_is_rejected():
    with pytest.raises(ValueError):
        requires("write:everything")
    with pytest.raises(ValueError):
        AnkiConnectRegistry().register("x", permission="write:everything")
