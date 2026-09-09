"""
Pure-layer tests for the settings dialog. The Qt shell (open_settings) is
deliberately untested here - a faithful widget-tree stub would test the stub,
not the code - and is covered by the manual smoke checklist instead.
"""
from pathlib import Path

from tsunagi.adapters.config import DEFAULTS
from tsunagi.adapters.settings_dialog import (
    FIELDS,
    GATE_INFO,
    RESTART_KEYS,
    config_from_form,
    form_values_from_config,
    gate_rows,
    validate_values,
)

HIDDEN_KEYS = {"ankiconnect_import_offered", "config_version",
               "dev_watch_seconds", "gates", "ankiconnect_ignore_origins"}


class TestFieldSpec:
    def test_every_field_key_is_a_real_config_key(self):
        for f in FIELDS:
            assert f.key in DEFAULTS, f.key

    def test_hidden_keys_never_appear_in_the_form(self):
        assert HIDDEN_KEYS.isdisjoint({f.key for f in FIELDS})

    def test_form_plus_hidden_covers_the_whole_config(self):
        # A new DEFAULTS key must be placed: either in the form or explicitly
        # hidden. This fails until that decision is made.
        assert {f.key for f in FIELDS} | HIDDEN_KEYS == set(DEFAULTS)

    def test_restart_keys_match_config_md_contract(self):
        # config.md: server-level keys are only read at server startup, so
        # the dialog restarts the embedded server when one changes.
        # dev_watch_seconds is startup-bound too but hidden from the form.
        assert RESTART_KEYS == {"enabled", "host", "port", "prefer_port",
                                "log_level", "op_timeout_seconds"}


class TestRoundTrip:
    def test_untouched_form_changes_nothing(self):
        cfg = dict(DEFAULTS)
        new_cfg, restart = config_from_form(cfg, form_values_from_config(cfg))
        assert new_cfg == DEFAULTS
        assert restart is False
        assert cfg == DEFAULTS  # input not mutated

    def test_live_key_change_needs_no_restart(self):
        values = form_values_from_config(DEFAULTS)
        values["api_key"] = "sekrit"
        new_cfg, restart = config_from_form(dict(DEFAULTS), values)
        assert new_cfg["api_key"] == "sekrit"
        assert restart is False

    def test_restart_key_change_is_flagged(self):
        for key, value in (("port", 8765), ("enabled", False)):
            values = form_values_from_config(DEFAULTS)
            values[key] = value
            new_cfg, restart = config_from_form(dict(DEFAULTS), values)
            assert new_cfg[key] == value
            assert restart is True, key

    def test_whitespace_only_text_edit_is_not_a_change(self):
        values = form_values_from_config(DEFAULTS)
        values["host"] = f"  {DEFAULTS['host']}  "
        new_cfg, restart = config_from_form(dict(DEFAULTS), values)
        assert new_cfg["host"] == DEFAULTS["host"]
        assert restart is False

    def test_internal_keys_pass_through_verbatim(self):
        cfg = dict(DEFAULTS)
        cfg["ankiconnect_import_offered"] = True
        cfg["ankiconnect_ignore_origins"] = ["https://ignored.test", ["nested"]]
        values = form_values_from_config(cfg)
        values["api_key"] = "k"
        new_cfg, _ = config_from_form(cfg, values)
        assert new_cfg["ankiconnect_import_offered"] is True
        assert new_cfg["ankiconnect_ignore_origins"] == cfg["ankiconnect_ignore_origins"]
        assert new_cfg["config_version"] == DEFAULTS["config_version"]
        assert new_cfg["dev_watch_seconds"] == DEFAULTS["dev_watch_seconds"]


class TestMediaMib:
    def test_default_shows_as_64(self):
        assert form_values_from_config(DEFAULTS)["media_max_bytes"] == 64

    def test_edited_value_is_stored_in_bytes(self):
        values = form_values_from_config(DEFAULTS)
        values["media_max_bytes"] = 32
        new_cfg, restart = config_from_form(dict(DEFAULTS), values)
        assert new_cfg["media_max_bytes"] == 32 * 1024 * 1024
        assert restart is False

    def test_untouched_non_mib_multiple_survives_exactly(self):
        cfg = dict(DEFAULTS)
        cfg["media_max_bytes"] = 70000000  # not a whole MiB
        new_cfg, _ = config_from_form(cfg, form_values_from_config(cfg))
        assert new_cfg["media_max_bytes"] == 70000000


class TestCors:
    def test_parsing_strips_dedupes_and_keeps_order(self):
        values = form_values_from_config(DEFAULTS)
        values["cors_allowlist"] = "  https://a.test \n\n https://b.test\nhttps://a.test\n"
        new_cfg, restart = config_from_form(dict(DEFAULTS), values)
        assert new_cfg["cors_allowlist"] == ["https://a.test", "https://b.test"]
        assert restart is False

    def test_star_passes_through(self):
        values = form_values_from_config(DEFAULTS)
        values["cors_allowlist"] = "*"
        new_cfg, _ = config_from_form(dict(DEFAULTS), values)
        assert new_cfg["cors_allowlist"] == ["*"]

    def test_whitespace_only_edit_is_not_a_change(self):
        values = form_values_from_config(DEFAULTS)
        values["cors_allowlist"] = "\n" + values["cors_allowlist"] + "  \n"
        new_cfg, _ = config_from_form(dict(DEFAULTS), values)
        assert new_cfg["cors_allowlist"] == DEFAULTS["cors_allowlist"]


class TestGates:
    def test_unknown_gate_renders_and_round_trips(self):
        cfg = dict(DEFAULTS)
        cfg["gates"] = {**DEFAULTS["gates"], "future_gate": True}
        rows = gate_rows(cfg)
        row = next(r for r in rows if r[0] == "future_gate")
        assert row[1] == "future_gate"  # raw key as label fallback
        assert row[3] is True
        new_cfg, _ = config_from_form(cfg, form_values_from_config(cfg))
        assert new_cfg["gates"]["future_gate"] is True

    def test_toggling_one_gate_leaves_siblings(self):
        values = form_values_from_config(DEFAULTS)
        values["gates"] = {**values["gates"], "cards_set_memory_state": True}
        new_cfg, restart = config_from_form(dict(DEFAULTS), values)
        assert new_cfg["gates"]["cards_set_memory_state"] is True
        assert new_cfg["gates"]["media_allow_local_path"] is False
        assert restart is False

    def test_result_gates_dict_is_a_fresh_object(self):
        cfg = dict(DEFAULTS)  # shallow: cfg["gates"] IS DEFAULTS["gates"]
        values = form_values_from_config(cfg)
        values["gates"] = {**values["gates"], "media_allow_local_path": True}
        new_cfg, _ = config_from_form(cfg, values)
        assert new_cfg["gates"] is not DEFAULTS["gates"]
        assert new_cfg["gates"] is not cfg["gates"]
        assert DEFAULTS["gates"]["media_allow_local_path"] is False


class TestValidation:
    def test_defaults_validate_clean(self):
        assert validate_values(form_values_from_config(DEFAULTS)) == []

    def test_empty_host_is_an_error(self):
        values = form_values_from_config(DEFAULTS)
        values["host"] = "   "
        assert any("Host" in e for e in validate_values(values))

    def test_out_of_range_int_is_an_error(self):
        values = form_values_from_config(DEFAULTS)
        values["prefer_port"] = 0
        assert any("Preferred port" in e for e in validate_values(values))


class TestDocDrift:
    def test_every_default_gate_has_a_label_and_docs(self):
        config_md = (Path(__file__).parent.parent / "config.md").read_text(encoding="utf-8")
        for key in DEFAULTS["gates"]:
            assert key in GATE_INFO, f"gate {key} needs a GATE_INFO entry"
            assert key in config_md, f"gate {key} is undocumented in config.md"


class TestAnkiConnectSettings:
    def test_detection_does_not_change_addons(self):
        from types import SimpleNamespace

        from tsunagi.adapters.dialogs import ANKICONNECT_ID, ankiconnect_status

        for enabled in (True, False):
            manager = SimpleNamespace(
                allAddons=lambda: [ANKICONNECT_ID],
                addon_meta=lambda _name, enabled=enabled: SimpleNamespace(enabled=enabled),
                getConfig=lambda _name: {},
            )
            assert ankiconnect_status(manager) == {
                "installed": True, "enabled": enabled, "config_available": True,
            }
        assert ankiconnect_status(SimpleNamespace(allAddons=lambda: [])) == {
            "installed": False, "enabled": False, "config_available": False,
        }

    def test_import_merges_origins_without_importing_ports_or_gates(self):
        from tsunagi.adapters.dialogs import ankiconnect_import_changes

        original = {"api_key": "old", "cors_allowlist": ["http://existing"],
                    "port": 7777, "gates": {"media_allow_local_path": False}}
        ac = {"apiKey": "new", "webCorsOriginList": ["http://existing", "http://new"],
              "webBindPort": 8765, "gates": {"media_allow_local_path": True}}
        result = {**original, **ankiconnect_import_changes(original, ac)}
        assert result["api_key"] == "new"
        assert result["cors_allowlist"] == ["http://existing", "http://new"]
        assert result["port"] == 7777
        assert result["gates"] == original["gates"]
        assert original["cors_allowlist"] == ["http://existing"]
        assert {**original, **ankiconnect_import_changes(original, {})}["api_key"] == "old"

    def test_saving_unrelated_settings_does_not_inspect_or_disable_ankiconnect(self, monkeypatch):
        from types import SimpleNamespace

        from tsunagi.adapters import settings_dialog as dialog

        calls = []
        monkeypatch.setattr(dialog, "apply_config", lambda mw, cfg, **kwargs: calls.append(cfg))
        dialog.save_settings(SimpleNamespace(), {"port": 7777})
        assert calls == [{"port": 7777}]

    def test_explicit_import_disables_once_before_saving(self, monkeypatch):
        from types import SimpleNamespace

        from tsunagi.adapters import settings_dialog as dialog
        from tsunagi.adapters.dialogs import ANKICONNECT_ID

        calls = []
        monkeypatch.setattr(dialog, "_check_handover_port", lambda cfg: None)
        for enabled in (True, False):
            calls.clear()
            manager = SimpleNamespace(
                allAddons=lambda: [ANKICONNECT_ID],
                addon_meta=lambda _name, enabled=enabled: SimpleNamespace(enabled=enabled),
                getConfig=lambda _name: {},
                toggleEnabled=lambda name, enable: calls.append((name, enable)),
            )
            monkeypatch.setattr(dialog, "apply_config", lambda *args, **kwargs: calls.append("saved"))
            dialog.save_settings(SimpleNamespace(addonManager=manager), {}, disable_ankiconnect=True)
            assert calls == ([(ANKICONNECT_ID, False), "saved"] if enabled else ["saved"])

    def test_disable_failure_does_not_save_imported_settings(self, monkeypatch):
        from types import SimpleNamespace

        import pytest

        from tsunagi.adapters import settings_dialog as dialog
        from tsunagi.adapters.dialogs import ANKICONNECT_ID

        writes = []
        previous = {"api_key": "old", "port": 7777}

        def fail(*args, **kwargs):
            raise OSError("cannot write addon metadata")

        manager = SimpleNamespace(
            allAddons=lambda: [ANKICONNECT_ID],
            addon_meta=lambda _name: SimpleNamespace(enabled=True),
            getConfig=lambda _name: previous,
            toggleEnabled=fail,
        )
        monkeypatch.setattr(dialog, "apply_config", lambda mw, cfg, **kwargs: writes.append(cfg))
        with pytest.raises(OSError, match="cannot write"):
            dialog.save_settings(SimpleNamespace(addonManager=manager), {"api_key": "new"},
                                 disable_ankiconnect=True)
        assert writes == []

    def test_removed_addon_does_not_save_import(self, monkeypatch):
        from types import SimpleNamespace

        import pytest

        from tsunagi.adapters import settings_dialog as dialog

        def fail(*args, **kwargs):
            raise AssertionError("Settings must not be written")

        monkeypatch.setattr(dialog, "apply_config", fail)
        with pytest.raises(ValueError, match="no longer installed"):
            dialog.save_settings(SimpleNamespace(addonManager=SimpleNamespace(allAddons=lambda: [])),
                                 {}, disable_ankiconnect=True)


class TestAnkiConnectPortHandover:
    def test_explicit_import_copies_port_and_enables_tsunagi(self):
        from tsunagi.adapters.dialogs import ankiconnect_import_changes

        cfg = {"enabled": False, "port": 7777}
        ac = {"webBindPort": 8765}
        assert "port" not in ankiconnect_import_changes(cfg, ac)
        changes = ankiconnect_import_changes(cfg, ac, include_port=True)
        assert changes["port"] == 8765
        assert changes["enabled"] is True
        assert cfg == {"enabled": False, "port": 7777}

    def test_invalid_import_port_is_rejected_before_form_clamping(self):
        import pytest

        from tsunagi.adapters.dialogs import ankiconnect_import_changes

        for port in (True, 0, -1, 65536, "8765", []):
            with pytest.raises(ValueError, match="AnkiConnect's port"):
                ankiconnect_import_changes({}, {"webBindPort": port}, include_port=True)

    def test_live_listener_is_released_and_can_be_restored(self, monkeypatch):
        import socket
        import sys
        from types import SimpleNamespace

        from tsunagi.adapters.dialogs import ANKICONNECT_ID, stop_ankiconnect_server

        class Server:
            def __init__(self):
                self.sock = None
                self.port = 0
                self.listen()

            def listen(self):
                self.sock = socket.socket()
                self.sock.bind(("127.0.0.1", self.port))
                self.port = self.sock.getsockname()[1]
                self.sock.listen()

            def close(self):
                self.sock.close()
                self.sock = None

        server = Server()
        events = []
        timer = SimpleNamespace(isActive=lambda: True, interval=lambda: 25,
                                stop=lambda: events.append("stop"),
                                start=lambda interval: events.append(interval))
        monkeypatch.setitem(sys.modules, ANKICONNECT_ID,
                            SimpleNamespace(ac=SimpleNamespace(server=server, timer=timer)))
        try:
            restore = stop_ankiconnect_server()
            assert server.sock is None
            assert events == ["stop"]
            with socket.socket() as replacement:
                replacement.bind(("127.0.0.1", server.port))
                replacement.listen()
            restore()
            assert server.sock is not None
            assert events == ["stop", 25]
        finally:
            if server.sock is not None:
                server.close()

    def test_busy_port_rolls_back_disable_and_runtime_before_saving(self, monkeypatch):
        import socket
        from types import SimpleNamespace

        import pytest

        from tsunagi.adapters import dialogs
        from tsunagi.adapters import settings_dialog as dialog

        events = []
        manager = SimpleNamespace(
            allAddons=lambda: [dialogs.ANKICONNECT_ID],
            addon_meta=lambda _name: SimpleNamespace(enabled=True),
            getConfig=lambda _name: {},
            toggleEnabled=lambda name, enable: events.append(("enabled", enable)),
        )
        monkeypatch.setattr(dialogs, "stop_ankiconnect_server",
                            lambda: events.append("stop") or (lambda: events.append("restore")))
        monkeypatch.setattr(dialog, "apply_config", lambda *a, **kw: events.append("save"))
        with socket.socket() as other_server:
            other_server.bind(("127.0.0.1", 0))
            other_server.listen()
            cfg = {"host": "127.0.0.1", "port": other_server.getsockname()[1]}
            with pytest.raises(ValueError, match="still in use"):
                dialog.save_settings(SimpleNamespace(addonManager=manager), cfg,
                                     disable_ankiconnect=True)
        assert events == [("enabled", False), "stop", ("enabled", True), "restore"]

    def test_config_write_failure_restores_settings_metadata_and_server(self, monkeypatch):
        from types import SimpleNamespace

        import pytest

        from tsunagi.adapters import dialogs
        from tsunagi.adapters import settings_dialog as dialog

        previous, new = {"api_key": "old"}, {"api_key": "new"}
        events = []
        manager = SimpleNamespace(
            allAddons=lambda: [dialogs.ANKICONNECT_ID],
            addon_meta=lambda _name: SimpleNamespace(enabled=True),
            getConfig=lambda _name: previous,
            toggleEnabled=lambda name, enable: events.append(("enabled", enable)),
        )

        def apply(mw, cfg, **kwargs):
            events.append(cfg)
            if cfg == new:
                raise OSError("config write failed")

        monkeypatch.setattr(dialog, "apply_config", apply)
        monkeypatch.setattr(dialog, "_check_handover_port", lambda cfg: None)
        monkeypatch.setattr(dialogs, "stop_ankiconnect_server",
                            lambda: events.append("stop") or (lambda: events.append("restore")))
        with pytest.raises(OSError, match="config write failed"):
            dialog.save_settings(SimpleNamespace(addonManager=manager), new, disable_ankiconnect=True)
        assert events == [("enabled", False), "stop", new, previous, ("enabled", True), "restore"]
