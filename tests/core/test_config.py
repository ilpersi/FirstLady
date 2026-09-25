"""Tests for src.core.config.ConfigManager - pure given a temp config dir.

Uses a fresh ConfigManager(config_dir=tmp_path) rather than the real,
tracked CONFIG singleton, so these tests never touch the live config files.
"""
import json

from src.core.config import ConfigManager


def _write(tmp_path, config=None, automation=None):
    if config is not None:
        (tmp_path / "config.json").write_text(json.dumps(config))
    if automation is not None:
        (tmp_path / "automation.json").write_text(json.dumps(automation))


class TestLoadConfigs:
    def test_valid_files_load_successfully(self, tmp_path):
        _write(tmp_path, config={"debug_mode": True, "foo": "bar"}, automation={"time_checks": {"a": 1}})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm["foo"] == "bar"
        assert cm.debug_mode is True
        assert cm.time_checks == {"a": 1}

    def test_missing_files_fall_back_to_empty_dicts(self, tmp_path):
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm._config == {}
        assert cm._automation_config == {}
        assert cm.time_checks == {}
        assert cm.scheduled_events == {}

    def test_malformed_json_falls_back_to_empty_dict(self, tmp_path):
        (tmp_path / "config.json").write_text("{not valid json")
        (tmp_path / "automation.json").write_text("{not valid json")
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm._config == {}
        assert cm._automation_config == {}

    def test_missing_files_does_not_raise(self, tmp_path):
        # Constructing against a directory with no config files at all must
        # not propagate an exception - errors are logged, not raised.
        ConfigManager(config_dir=str(tmp_path / "does_not_exist"))


class TestGetItemAndGet:
    def test_getitem_missing_key_returns_empty_dict(self, tmp_path):
        _write(tmp_path, config={}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm["nonexistent"] == {}

    def test_getitem_present_key(self, tmp_path):
        _write(tmp_path, config={"match_threshold": 0.8}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm["match_threshold"] == 0.8

    def test_get_returns_default_when_missing(self, tmp_path):
        _write(tmp_path, config={}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm.get("missing", "fallback") == "fallback"

    def test_get_returns_none_default_when_missing_and_unspecified(self, tmp_path):
        _write(tmp_path, config={}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm.get("missing") is None


class TestProperties:
    def test_debug_mode_defaults_false(self, tmp_path):
        _write(tmp_path, config={}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm.debug_mode is False

    def test_debug_mode_coerced_to_bool(self, tmp_path):
        _write(tmp_path, config={"debug_mode": 1}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm.debug_mode is True

    def test_control_list_defaults_when_absent(self, tmp_path):
        _write(tmp_path, config={}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm.control_list == {"whitelist": {"alliance": []}, "blacklist": {"alliance": []}}

    def test_control_list_uses_configured_value(self, tmp_path):
        _write(tmp_path, config={"control_list": {"whitelist": {"alliance": ["ABC"]}, "blacklist": {"alliance": []}}}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm.control_list["whitelist"]["alliance"] == ["ABC"]

    def test_adb_defaults_when_absent(self, tmp_path):
        _write(tmp_path, config={}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm.adb == {"host": "", "port": -1, "binary_path": "adb", "enforce_connection": False}

    def test_adb_uses_configured_value(self, tmp_path):
        _write(tmp_path, config={"adb": {"host": "1.2.3.4", "port": 5555, "binary_path": "adb", "enforce_connection": True}}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm.adb["host"] == "1.2.3.4"

    def test_time_checks_and_scheduled_events_defaults(self, tmp_path):
        _write(tmp_path, config={}, automation={})
        cm = ConfigManager(config_dir=str(tmp_path))
        assert cm.time_checks == {}
        assert cm.scheduled_events == {}
