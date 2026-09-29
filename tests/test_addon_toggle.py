"""Turning Tsunagi off in Tools -> Add-ons offers to stop its server now."""
from types import SimpleNamespace

from tsunagi.adapters.addon_toggle import ServerSwitch, watch_own_toggle


class Manager:
    """Anki's AddonManager, as far as toggleEnabled is concerned."""

    def __init__(self):
        self.enabled = {"tsunagi": True, "other": True}
        self.calls = []

    def toggleEnabled(self, module, enable=None):
        self.calls.append(module)
        self.enabled[module] = (not self.enabled[module]) if enable is None else enable

    def addon_meta(self, module):
        return SimpleNamespace(enabled=self.enabled[module])


def switch(running=True, answer=True):
    log = []
    state = {"running": running}

    def stop():
        log.append("stop")
        state["running"] = False

    def start():
        log.append("start")
        state["running"] = True

    def ask():
        log.append("ask")
        return answer

    return ServerSwitch(running=lambda: state["running"], ask_to_stop=ask, stop=stop, start=start), log


def test_turning_tsunagi_off_asks_and_stops_the_server_and_turning_it_on_restarts_it():
    manager, (server, log) = Manager(), switch()
    assert watch_own_toggle(manager, "tsunagi", server)
    manager.toggleEnabled("tsunagi")
    assert manager.enabled["tsunagi"] is False and log == ["ask", "stop"]
    manager.toggleEnabled("tsunagi", True)
    assert log == ["ask", "stop", "start"]


def test_keeping_it_running_or_turning_on_a_running_server_changes_nothing():
    manager, (server, log) = Manager(), switch(answer=False)
    watch_own_toggle(manager, "tsunagi", server)
    manager.toggleEnabled("tsunagi")
    manager.toggleEnabled("tsunagi")
    assert log == ["ask"]   # declined; turning it back on doesn't start a second server


def test_other_add_ons_and_a_stopped_server_are_left_alone():
    manager, (server, log) = Manager(), switch(running=False)
    watch_own_toggle(manager, "tsunagi", server)
    manager.toggleEnabled("other")
    manager.toggleEnabled("tsunagi")
    assert log == [] and manager.calls == ["other", "tsunagi"]   # Anki's own toggle still ran


def test_a_manager_without_toggle_enabled_is_not_wrapped():
    assert watch_own_toggle(SimpleNamespace(), "tsunagi", lambda enabled: None) is False
