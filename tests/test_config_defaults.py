import json
from pathlib import Path

from tsunagi.adapters.config import DEFAULTS, _migrate

ROOT = Path(__file__).resolve().parents[1]


def test_config_json_matches_defaults():
    # config.json is what Anki's "Restore Defaults" restores; keep it in
    # lockstep with the DEFAULTS dict used by load_config.
    shipped = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assert shipped == DEFAULTS


class TestMigrate:
    def test_empty_config_fills_all_defaults(self):
        cfg, changed = _migrate({})
        assert changed
        assert cfg == DEFAULTS

    def test_legacy_token_dropped_not_copied(self):
        cfg, changed = _migrate({"token": "auto-minted-garbage"})
        assert changed
        assert "token" not in cfg
        assert cfg["api_key"] == ""  # auth stays OFF for upgraders

    def test_migrated_config_is_stable(self):
        cfg, _ = _migrate({})
        again, changed = _migrate(dict(cfg))
        assert not changed
        assert again == cfg

    def test_version_bumped(self):
        cfg = dict(DEFAULTS)
        cfg["config_version"] = 1
        cfg, changed = _migrate(cfg)
        assert changed
        assert cfg["config_version"] == 3

    def test_v2_install_gains_localhost_allowlist(self):
        # Pre-v3 installs have an empty allowlist, which blocks browser
        # extensions (Yomitan); the migration adds AnkiConnect's default.
        cfg, changed = _migrate({**DEFAULTS, "cors_allowlist": [], "config_version": 2})
        assert changed
        assert cfg["cors_allowlist"] == ["http://localhost"]

    def test_migration_keeps_user_origins(self):
        cfg, _ = _migrate({**DEFAULTS, "cors_allowlist": ["https://mine.test"],
                           "config_version": 2})
        assert cfg["cors_allowlist"] == ["http://localhost", "https://mine.test"]

    def test_user_values_preserved(self):
        cfg, _ = _migrate({"prefer_port": 8888, "api_key": "mine"})
        assert cfg["prefer_port"] == 8888
        assert cfg["api_key"] == "mine"
