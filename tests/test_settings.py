from types import SimpleNamespace

from tsunagi.adapters.config import DEFAULTS
from tsunagi.adapters.settings import Settings, apply_config, settings


class TestSettings:
    def test_update_merges_and_persists_full_dict(self):
        seen = []
        s = Settings({"a": 1}, persist=seen.append)
        s.update(b=2)
        assert s.get("a") == 1
        assert s.get("b") == 2
        assert seen == [{"a": 1, "b": 2}]

    def test_update_without_persist_does_not_crash(self):
        s = Settings({"a": 1})
        s.update(a=2)
        assert s.get("a") == 2

    def test_add_cors_origin_appends_once(self):
        seen = []
        s = Settings({"cors_allowlist": []}, persist=seen.append)
        s.add_cors_origin("https://x.test")
        s.add_cors_origin("https://x.test")
        assert s.get("cors_allowlist") == ["https://x.test"]
        assert len(seen) == 1  # second call is a no-op, nothing re-persisted

    def test_configure_replaces_values_keeps_identity(self):
        s = Settings({"api_key": ""})
        ref = s
        seen = []
        s.configure({"api_key": "k"}, persist=seen.append)
        assert ref is s
        assert ref.get("api_key") == "k"
        s.update(x=1)
        assert seen  # new persist callback active

    def test_is_origin_allowed(self):
        s = Settings({"cors_allowlist": ["https://a.test"]})
        assert s.is_origin_allowed("https://a.test")
        assert not s.is_origin_allowed("https://b.test")
        s.update(cors_allowlist=["*"])
        assert s.is_origin_allowed("https://anything.test")

    def test_localhost_entry_covers_extensions_and_loopback(self):
        # AnkiConnect semantics: the "http://localhost" entry also allows
        # 127.0.0.1 origins and browser extensions (this is what makes
        # Yomitan work with no setup).
        s = Settings({"cors_allowlist": ["http://localhost"]})
        assert s.is_origin_allowed("chrome-extension://likgccmbimhjbgkjambclfkhldnlhbnn")
        assert s.is_origin_allowed("moz-extension://abc")
        assert s.is_origin_allowed("safari-web-extension://abc")
        assert s.is_origin_allowed("http://127.0.0.1")
        assert s.is_origin_allowed("http://127.0.0.1:8080")
        assert not s.is_origin_allowed("https://evil.test")

    def test_extensions_blocked_without_localhost_entry(self):
        s = Settings({"cors_allowlist": ["https://a.test"]})
        assert not s.is_origin_allowed("chrome-extension://abc")

    def test_snapshot_is_a_copy(self):
        s = Settings({"a": 1})
        snap = s.snapshot()
        snap["a"] = 99
        assert s.get("a") == 1


def fake_mw(writes):
    """addonManager records writeConfig calls; taskman runs inline."""
    return SimpleNamespace(
        addonManager=SimpleNamespace(
            writeConfig=lambda pkg, cfg: writes.append((pkg, cfg))),
        taskman=SimpleNamespace(run_on_main=lambda fn: fn()),
    )


class TestApplyConfig:
    def test_write_true_always_writes_and_configures(self, reset_settings):
        writes = []
        cfg = dict(DEFAULTS)
        cfg["api_key"] = "sekrit"
        migrated = apply_config(fake_mw(writes), cfg, write=True)
        assert len(writes) == 1
        assert writes[0][1]["api_key"] == "sekrit"
        assert migrated["api_key"] == "sekrit"
        assert settings.get("api_key") == "sekrit"

    def test_write_false_skips_write_when_nothing_migrated(self, reset_settings):
        writes = []
        apply_config(fake_mw(writes), dict(DEFAULTS), write=False)
        assert writes == []
        assert settings.get("config_version") == DEFAULTS["config_version"]

    def test_write_false_still_writes_when_migration_changed(self, reset_settings):
        # A pre-v4 flat media_allow_local_path must be folded into gates and
        # the corrected dict written back, even on the no-write path.
        writes = []
        cfg = dict(DEFAULTS)
        cfg.pop("gates")
        cfg["media_allow_local_path"] = True
        cfg["config_version"] = 3
        migrated = apply_config(fake_mw(writes), cfg, write=False)
        assert len(writes) == 1
        assert migrated["gates"]["media_allow_local_path"] is True
        assert "media_allow_local_path" not in migrated
        assert settings.gate_enabled("media_allow_local_path")

    def test_persist_callback_writes_through_addon_manager(self, reset_settings):
        writes = []
        apply_config(fake_mw(writes), dict(DEFAULTS), write=True)
        writes.clear()
        settings.update(api_key="later")
        assert len(writes) == 1
        assert writes[0][1]["api_key"] == "later"

    def test_input_dict_is_not_mutated(self, reset_settings):
        cfg = dict(DEFAULTS)
        cfg.pop("gates")
        before = dict(cfg)
        apply_config(fake_mw([]), cfg, write=False)
        assert cfg == before
