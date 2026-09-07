"""Profile lifecycle ordering without a live Qt event loop or HTTP server."""

import sys
from collections import deque
from types import ModuleType, SimpleNamespace

import pytest

from tsunagi.adapters.anki import collection


@pytest.fixture
def profile_ui(monkeypatch):
    callbacks = deque()
    events = []
    state = SimpleNamespace(visible=True, returned=False, delayed_unload=False)

    def on_main(fn):
        result = fn()
        state.returned = True
        return result

    def unload():
        # A server drain here must not be waiting on this main-thread call.
        assert state.returned, "profile unload began before caller was released"
        events.append("unload")
        if not state.delayed_unload:
            state.visible = False

    def load(name):
        assert state.returned
        assert not state.visible, "loaded target before old profile closed"
        events.append(("load", name))
        mw.pm.name = name

    def show():
        events.append("show")
        state.visible = True

    mw = SimpleNamespace(
        pm=SimpleNamespace(name="Source", profiles=lambda: ["Source", "Target"],
                           load=load),
        isVisible=lambda: state.visible,
        unloadProfileAndShowProfileManager=unload,
        loadProfile=show,
        profileDiag=SimpleNamespace(closeWithoutQuitting=lambda: events.append("close")),
    )
    qt = ModuleType("aqt.qt")
    qt.QTimer = SimpleNamespace(singleShot=lambda ms, fn: callbacks.append((ms, fn)))
    monkeypatch.setitem(sys.modules, "aqt.qt", qt)
    monkeypatch.setattr(sys.modules["aqt"], "mw", mw)
    monkeypatch.setattr(collection, "call_on_main", on_main)
    return state, callbacks, events


def test_visible_switch_releases_caller_before_shutdown_and_closes_dialog(profile_ui):
    _, callbacks, events = profile_ui
    assert collection.load_profile("Target") is True
    assert events == []
    _, begin = callbacks.popleft()
    begin()
    assert events == ["unload", ("load", "Target"), "show", "close"]
    assert not callbacks


def test_switch_waits_for_async_unload_before_loading_target(profile_ui):
    state, callbacks, events = profile_ui
    state.delayed_unload = True
    assert collection.load_profile("Target") is True
    callbacks.popleft()[1]()
    assert events == ["unload"]
    callbacks.popleft()[1]()
    assert events == ["unload"]
    state.visible = False
    callbacks.popleft()[1]()
    assert events == ["unload", ("load", "Target"), "show", "close"]


def test_switch_from_profile_manager_closes_dialog(profile_ui):
    state, callbacks, events = profile_ui
    state.visible = False
    assert collection.load_profile("Target") is True
    assert events == []
    callbacks.popleft()[1]()
    assert events == [("load", "Target"), "show", "close"]


@pytest.mark.parametrize("name, accepted", [("Missing", False), ("Source", True)])
def test_unknown_and_current_profiles_do_not_schedule_switch(profile_ui, name, accepted):
    _, callbacks, events = profile_ui
    assert collection.load_profile(name) is accepted
    assert not callbacks
    assert events == []
