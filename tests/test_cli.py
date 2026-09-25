"""Tests for cli.py.

`cli.py` reads config/automation.json AT MODULE IMPORT TIME to build both
ROUTINE_CONFIG (used by run_single_routine) and the argparse `routine_name`
choices. Tests that need custom automation.json contents chdir to a tmp_path
config tree and importlib.reload(cli) there; a teardown reloads it again
back in the real repo cwd so later tests (and other test modules importing
`cli` fresh) see the real config again.
"""
import importlib
import json
import sys
from unittest.mock import patch, MagicMock

import pytest

import cli


@pytest.fixture
def reloaded_cli(tmp_path, monkeypatch):
    """Reload cli.py against a tmp_path config/automation.json, then reload
    it back against the real repo config on teardown."""

    def _reload_with(automation_config):
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "automation.json").write_text(json.dumps(automation_config))
        monkeypatch.chdir(tmp_path)
        importlib.reload(cli)
        return cli

    yield _reload_with
    monkeypatch.undo()
    importlib.reload(cli)


class TestGetRoutineConfig:
    def test_filters_out_null_interval_entries(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "automation.json").write_text(json.dumps({
            "time_checks": {
                "enabled_one": {"handler": "a.b.C", "interval": 60},
                "disabled_one": {"handler": "a.b.D", "interval": None},
            },
            "scheduled_events": {},
        }))
        monkeypatch.chdir(tmp_path)
        result = cli.get_routine_config()
        assert set(result.keys()) == {"enabled_one"}

    def test_missing_file_returns_empty_dict(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no config/ directory at all
        assert cli.get_routine_config() == {}

    def test_malformed_file_returns_empty_dict(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "automation.json").write_text("{not json")
        monkeypatch.chdir(tmp_path)
        assert cli.get_routine_config() == {}


class TestRoutineConfigReload:
    def test_argparse_choices_reflect_filtered_routines(self, reloaded_cli):
        reloaded = reloaded_cli({
            "time_checks": {
                "runnable": {"handler": "a.b.C", "interval": 30},
                "disabled": {"handler": "a.b.D", "interval": None},
            },
            "scheduled_events": {},
        })
        assert set(reloaded.ROUTINE_CONFIG.keys()) == {"runnable"}
        routine_action = next(a for a in reloaded.parser._actions if a.dest == "routine_name")
        assert routine_action.choices == ["runnable"]


class TestRunSingleRoutine:
    def test_routine_not_in_config_returns_false(self):
        with patch.dict(cli.ROUTINE_CONFIG, {}, clear=True):
            assert cli.run_single_routine("device1", "nonexistent") is False

    def test_happy_path_creates_handler_and_starts_it(self):
        fake_handler = MagicMock()
        fake_handler.start.return_value = True
        fake_routine_config = {"secretary": {"handler": "a.b.SecretaryRoutine", "interval": 40}}

        with patch.dict(cli.ROUTINE_CONFIG, fake_routine_config, clear=True), \
             patch("cli.MainAutomation") as mock_automation, \
             patch.object(cli.HandlerFactory, "create_handler", return_value=fake_handler) as mock_create:
            result = cli.run_single_routine("device1", "secretary")

        assert result is True
        fake_handler.start.assert_called_once()
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert args[0] == "a.b.SecretaryRoutine"
        assert args[1] == "device1"
        assert kwargs["automation"] is mock_automation.return_value

    def test_handler_creation_failure_returns_false(self):
        fake_routine_config = {"secretary": {"handler": "a.b.SecretaryRoutine", "interval": 40}}
        with patch.dict(cli.ROUTINE_CONFIG, fake_routine_config, clear=True), \
             patch("cli.MainAutomation"), \
             patch.object(cli.HandlerFactory, "create_handler", return_value=None):
            assert cli.run_single_routine("device1", "secretary") is False

    def test_exception_is_caught_and_returns_false(self):
        fake_routine_config = {"secretary": {"handler": "a.b.SecretaryRoutine", "interval": 40}}
        with patch.dict(cli.ROUTINE_CONFIG, fake_routine_config, clear=True), \
             patch("cli.MainAutomation", side_effect=RuntimeError("boom")):
            assert cli.run_single_routine("device1", "secretary") is False


class TestMainNoDeviceFound:
    def test_exits_with_error_when_no_device_connected(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "auto"])
        with patch("cli.verify_emulator_running"), \
             patch("cli.get_connected_device", return_value=None), \
             patch("cli.setup_logging"):
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
        assert exc_info.value.code == 1


class TestMainRoutineCommand:
    def test_routine_command_without_routine_name_returns_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "routine"])
        with patch("cli.verify_emulator_running"), \
             patch("cli.get_connected_device", return_value="device1"), \
             patch("cli.setup_logging"), \
             patch("cli.signal.signal"), \
             patch.object(cli.cleanup_manager, "cleanup"):
            result = cli.main()
        assert result == 1

    def test_routine_command_runs_and_returns_0_on_success(self, monkeypatch):
        fake_routine_config = {"secretary": {"handler": "a.b.SecretaryRoutine", "interval": 40}}
        monkeypatch.setattr(sys, "argv", ["cli.py", "routine", "secretary"])
        with patch.dict(cli.ROUTINE_CONFIG, fake_routine_config, clear=True), \
             patch("cli.verify_emulator_running"), \
             patch("cli.get_connected_device", return_value="device1"), \
             patch("cli.setup_logging"), \
             patch("cli.signal.signal"), \
             patch("cli.run_single_routine", return_value=True) as mock_run, \
             patch.object(cli.cleanup_manager, "cleanup"):
            result = cli.main()
        assert result == 0
        mock_run.assert_called_once_with("device1", "secretary")


class TestMainAutoCommand:
    def test_auto_command_starts_console_and_runs_automation(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "auto"])
        fake_automation = MagicMock()
        fake_automation.run.return_value = True
        fake_console = MagicMock()

        with patch("cli.verify_emulator_running"), \
             patch("cli.get_connected_device", return_value="device1"), \
             patch("cli.setup_logging"), \
             patch("cli.signal.signal"), \
             patch("cli.InteractiveConsole", return_value=fake_console) as mock_console_cls, \
             patch("cli.MainAutomation", return_value=fake_automation) as mock_automation_cls, \
             patch.object(cli.cleanup_manager, "cleanup"):
            result = cli.main()

        assert result == 0
        mock_console_cls.assert_called_once_with("device1")
        fake_console.start.assert_called_once()
        fake_console.stop.assert_called_once()
        mock_automation_cls.assert_called_once()
        fake_automation.run.assert_called_once()


class TestMainResetCommand:
    def test_reset_command_calls_force_reset(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "reset"])
        fake_automation = MagicMock()
        fake_automation.force_reset.return_value = True

        with patch("cli.verify_emulator_running"), \
             patch("cli.get_connected_device", return_value="device1"), \
             patch("cli.setup_logging"), \
             patch("cli.signal.signal"), \
             patch("cli.MainAutomation", return_value=fake_automation), \
             patch.object(cli.cleanup_manager, "cleanup"):
            cli.main()

        fake_automation.force_reset.assert_called_once()

    def test_reset_command_exits_when_force_reset_fails(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "reset"])
        fake_automation = MagicMock()
        fake_automation.force_reset.return_value = False

        with patch("cli.verify_emulator_running"), \
             patch("cli.get_connected_device", return_value="device1"), \
             patch("cli.setup_logging"), \
             patch("cli.signal.signal"), \
             patch("cli.MainAutomation", return_value=fake_automation), \
             patch.object(cli.cleanup_manager, "cleanup"):
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
        assert exc_info.value.code == 1
