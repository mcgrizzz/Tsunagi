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


class TestResolveCaller:
    """Who a request is: an app by its key, else a No key row (6.5a)."""

    APPS = {"apps": [{"name": "Yomitan", "key": "yk", "group": "default"},
                     {"name": "Dashboard", "key": "dk", "group": "read_only"}]}

    def test_a_key_selects_its_app_and_group(self):
        caller = Settings(self.APPS).resolve_caller("dk", False)
        assert (caller.name, caller.group, caller.key) == ("Dashboard", "read_only", "dk")
        assert caller.grants == {"read", "events:changes"}

    def test_no_key_uses_the_row_for_where_it_came_from(self):
        s = Settings({})
        assert s.resolve_caller(None, True).group == "default"
        assert s.resolve_caller(None, False).group == "none"
        assert s.resolve_caller(None, False).grants == frozenset()

    def test_unknown_key_is_the_no_key_row(self):
        caller = Settings(self.APPS).resolve_caller("nope", True)
        assert caller.key is None and caller.group == "default"

    def test_unknown_group_grants_nothing(self):
        caller = Settings({"apps": [{"name": "X", "key": "k", "group": "gone"}]}).resolve_caller("k", True)
        assert caller.grants == frozenset()

    def test_edited_built_in_and_custom_groups(self):
        s = Settings({**self.APPS, "groups": {
            "default": {"name": "Default", "grants": ["read", "write:notes", "bogus"]},
            "tagger": {"name": "Tagger", "grants": ["read:notes", "write:tags"]}},
            "no_key_local_group": "tagger"})
        assert s.resolve_caller("yk", True).grants == {"read", "write:notes"}
        assert s.resolve_caller(None, True).group_name == "Tagger"


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
        # A pre-v4 flat media_allow_local_path must be dropped and the
        # corrected dict written back, even on the no-write path.
        writes = []
        cfg = dict(DEFAULTS)
        cfg.pop("gates")
        cfg["media_allow_local_path"] = True
        cfg["config_version"] = 3
        migrated = apply_config(fake_mw(writes), cfg, write=False)
        assert len(writes) == 1
        assert "media_allow_local_path" not in migrated
        assert settings.get("gates") == DEFAULTS["gates"]

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
