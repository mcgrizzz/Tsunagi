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
               "dev_watch_seconds", "gates"}


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
        values = form_values_from_config(cfg)
        values["api_key"] = "k"
        new_cfg, _ = config_from_form(cfg, values)
        assert new_cfg["ankiconnect_import_offered"] is True
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
