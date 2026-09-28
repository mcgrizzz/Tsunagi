"""macOS App Nap is off while the server runs (Anki leaves it to add-ons)."""
import logging
import sys
import types

import pytest

from tsunagi import app


@pytest.fixture()
def helper(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(disable_appnap=lambda: calls.append("off"),
                                 enable_appnap=lambda: calls.append("on"))
    monkeypatch.setitem(sys.modules, "aqt._macos_helper", types.SimpleNamespace(macos_helper=fake))
    return calls


def test_app_nap_is_off_while_serving_and_back_on_after(helper, monkeypatch):
    app._set_app_nap(allowed=False)
    monkeypatch.setattr(app._SERVER_STATE, "started", True)
    assert app.stop_server() is True
    assert helper == ["off", "on"]


def test_nothing_happens_off_macos(monkeypatch):
    monkeypatch.setitem(sys.modules, "aqt._macos_helper", types.SimpleNamespace(macos_helper=None))
    app._set_app_nap(allowed=False)  # no error, nothing to call


def test_an_old_helper_without_the_call_is_only_logged(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "aqt._macos_helper",
                        types.SimpleNamespace(macos_helper=types.SimpleNamespace()))
    with caplog.at_level(logging.WARNING):
        app._set_app_nap(allowed=False)
    assert "Could not turn off App Nap" in caplog.text
