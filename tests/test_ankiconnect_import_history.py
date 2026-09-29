"""Saved import history is separate from both prompt and add-on enabled state."""

import importlib
from datetime import datetime
from types import SimpleNamespace

import pytest

from tsunagi.adapters import dialogs, settings_dialog
from tsunagi.adapters.config import _migrate
from tsunagi.adapters.settings import Settings


@pytest.mark.parametrize("offered,installed,opens", [(False, True, True), (True, True, False),
                                                     (False, False, False)])
def test_startup_offer_opens_the_takeover_once(monkeypatch, offered, installed, opens):
    import aqt

    from tsunagi.adapters import settings_page

    saved, opened = [], []
    settings = Settings({"ankiconnect_import_offered": offered}, persist=saved.append)
    monkeypatch.setattr(importlib.import_module("tsunagi.adapters.settings"), "settings", settings)
    monkeypatch.setattr(aqt, "mw", SimpleNamespace(addonManager=SimpleNamespace(
        getConfig=lambda name: {"webBindPort": 8765} if installed else None)))
    monkeypatch.setattr(settings_page, "open_settings", lambda mw, **kw: opened.append(kw))
    dialogs.offer_ankiconnect_import()
    assert opened == ([{"offer_takeover": True}] if opens else [])
    # Remembered as soon as it is shown, whatever the answer.
    assert bool(saved and saved[-1]["ankiconnect_import_offered"]) == opens


def test_saved_reimport_updates_history_without_mutating_preview(monkeypatch):
    previous = {"ankiconnect_imported_at": "2025-01-01T00:00:00+00:00"}
    saved = []
    manager = SimpleNamespace(
        allAddons=lambda: [dialogs.ANKICONNECT_ID],
        addon_meta=lambda _name: SimpleNamespace(enabled=False),
        getConfig=lambda _name: previous,
    )
    monkeypatch.setattr(dialogs, "stop_ankiconnect_server", lambda: lambda: None)
    monkeypatch.setattr(settings_dialog, "_check_handover_port", lambda cfg: None)
    monkeypatch.setattr(settings_dialog, "apply_config", lambda mw, cfg, **kw: saved.append(cfg))
    preview = {**previous, "api_key": "imported"}
    settings_dialog.save_settings(SimpleNamespace(addonManager=manager), preview, disable_ankiconnect=True)
    assert saved[0]["ankiconnect_imported_at"] != previous["ankiconnect_imported_at"]
    assert saved[0]["ankiconnect_import_offered"] is True
    assert preview["ankiconnect_imported_at"] == previous["ankiconnect_imported_at"]


@pytest.mark.parametrize("offered", [True, False])
def test_migration_does_not_invent_past_imports(offered):
    cfg, _ = _migrate({"ankiconnect_import_offered": offered})
    assert cfg["ankiconnect_imported_at"] is None
    assert "Last imported" not in settings_dialog.import_history_text(cfg)


def test_history_shows_local_date_and_tolerates_invalid_metadata():
    recorded = "2026-09-11T12:34:00+00:00"
    expected = datetime.fromisoformat(recorded).astimezone().strftime("%d %b %Y at %H:%M")
    assert expected in settings_dialog.import_history_text({"ankiconnect_imported_at": recorded})
    assert settings_dialog.import_history_text({"ankiconnect_imported_at": "bad date"}) == "Unavailable"
