"""Saved import history is separate from both prompt and add-on enabled state."""

import importlib
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

from tsunagi.adapters import dialogs, settings_dialog
from tsunagi.adapters.config import _migrate
from tsunagi.adapters.settings import Settings


@pytest.mark.parametrize("accepted", [True, False])
def test_startup_offer_records_only_accepted_imports(monkeypatch, accepted):
    import aqt

    saved = []
    settings = Settings({"cors_allowlist": ["http://existing"]}, persist=saved.append)
    module = importlib.import_module("tsunagi.adapters.settings")
    monkeypatch.setattr(module, "settings", settings)
    monkeypatch.setattr(aqt, "mw", SimpleNamespace(addonManager=SimpleNamespace(
        getConfig=lambda _name: {"apiKey": "imported", "webCorsOriginList": ["http://imported"]},
    )))
    message_box = SimpleNamespace(
        StandardButton=SimpleNamespace(Yes=1),
        question=lambda *args: 1 if accepted else 0,
    )
    monkeypatch.setitem(sys.modules, "aqt.qt", SimpleNamespace(QMessageBox=message_box))
    dialogs.offer_ankiconnect_import()
    assert len(saved) == 1 and saved[0]["ankiconnect_import_offered"] is True
    if accepted:
        assert datetime.fromisoformat(saved[0]["ankiconnect_imported_at"]).utcoffset().total_seconds() == 0
        assert saved[0]["api_key"] == "imported"
        assert saved[0]["cors_allowlist"] == ["http://existing", "http://imported"]
    else:
        assert not saved[0].get("ankiconnect_imported_at")
    dialogs.offer_ankiconnect_import()
    assert len(saved) == 1


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
    expected = datetime.fromisoformat(recorded).astimezone().strftime("%Y-%m-%d %H:%M")
    assert expected in settings_dialog.import_history_text({"ankiconnect_imported_at": recorded})
    assert settings_dialog.import_history_text({"ankiconnect_imported_at": "bad date"}) == "Import history is unavailable."
