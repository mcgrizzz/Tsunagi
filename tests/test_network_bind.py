"""Tsunagi never listens beyond this computer without an API key."""
from types import SimpleNamespace

import pytest

from tsunagi import app as app_module
from tsunagi.adapters.config import DEFAULTS


@pytest.fixture
def fake_mw():
    return SimpleNamespace(
        addonManager=SimpleNamespace(setConfigUpdatedAction=lambda *a: None, writeConfig=lambda *a: None),
        mediaServer=SimpleNamespace(getPort=lambda: 34083),
        col=object(),
    )


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.97", "anki-box.local"])
def test_network_host_without_key_does_not_start(monkeypatch, capsys, fake_mw, reset_settings, host):
    monkeypatch.setattr(app_module, "load_config", lambda: {**DEFAULTS, "host": host, "api_key": ""})
    monkeypatch.setattr(app_module, "choose_port", lambda cfg: pytest.fail("reached binding"))
    app_module.start_server(fake_mw)
    assert not app_module._SERVER_STATE.started
    assert "needs an API key" in capsys.readouterr().out
