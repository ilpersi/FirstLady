"""Tests for src.automation.state.AutomationState.

Every test passes an explicit state_file under tmp_path so the tracked
state/automation_state.json is never touched.
"""
import json

from src.automation.state import AutomationState


class TestLoad:
    def test_missing_file_defaults_to_empty_state(self, tmp_path):
        state = AutomationState(state_file=tmp_path / "state.json")
        assert state.get_all_checks("time_checks") == {}
        assert state.get_all_checks("scheduled_events") == {}

    def test_missing_file_parent_dir_is_created(self, tmp_path):
        state_file = tmp_path / "nested" / "dir" / "state.json"
        AutomationState(state_file=state_file)
        assert state_file.parent.exists()

    def test_corrupt_json_falls_back_to_empty_state(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text("{not valid json")
        state = AutomationState(state_file=state_file)
        assert state.get_all_checks("time_checks") == {}
        assert state.get_all_checks("scheduled_events") == {}

    def test_valid_existing_file_is_loaded(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "time_checks": {"secretary": {"last_run": 123.0}},
            "scheduled_events": {},
        }))
        state = AutomationState(state_file=state_file)
        assert state.get_last_run("secretary") == 123.0


class TestGetSetLastRun:
    def test_get_last_run_missing_check_returns_none(self, tmp_path):
        state = AutomationState(state_file=tmp_path / "state.json")
        assert state.get_last_run("nonexistent") is None

    def test_set_then_get_last_run_time_checks(self, tmp_path):
        state = AutomationState(state_file=tmp_path / "state.json")
        state.set_last_run("secretary", 1000.0, "time_checks")
        assert state.get_last_run("secretary", "time_checks") == 1000.0

    def test_set_then_get_last_run_scheduled_events(self, tmp_path):
        state = AutomationState(state_file=tmp_path / "state.json")
        state.set_last_run("weekly_reset", 2000.0, "scheduled_events")
        assert state.get_last_run("weekly_reset", "scheduled_events") == 2000.0

    def test_set_last_run_creates_missing_check_type(self, tmp_path):
        state = AutomationState(state_file=tmp_path / "state.json")
        state.set_last_run("foo", 500.0, "brand_new_type")
        assert state.get_last_run("foo", "brand_new_type") == 500.0

    def test_set_last_run_overwrites_previous_value(self, tmp_path):
        state = AutomationState(state_file=tmp_path / "state.json")
        state.set_last_run("secretary", 1000.0, "time_checks")
        state.set_last_run("secretary", 2000.0, "time_checks")
        assert state.get_last_run("secretary", "time_checks") == 2000.0


class TestSave:
    def test_save_writes_valid_reloadable_json(self, tmp_path):
        state_file = tmp_path / "state.json"
        state = AutomationState(state_file=state_file)
        state.set_last_run("secretary", 1234.5, "time_checks")
        state.save()

        reloaded = AutomationState(state_file=state_file)
        assert reloaded.get_last_run("secretary", "time_checks") == 1234.5

    def test_save_produces_well_formed_json_on_disk(self, tmp_path):
        state_file = tmp_path / "state.json"
        state = AutomationState(state_file=state_file)
        state.set_last_run("secretary", 1.0, "time_checks")
        state.save()

        with open(state_file) as f:
            data = json.load(f)
        assert data["time_checks"]["secretary"]["last_run"] == 1.0


class TestGetAllChecks:
    def test_get_all_checks_returns_all_entries_of_type(self, tmp_path):
        state = AutomationState(state_file=tmp_path / "state.json")
        state.set_last_run("a", 1.0, "time_checks")
        state.set_last_run("b", 2.0, "time_checks")
        checks = state.get_all_checks("time_checks")
        assert set(checks.keys()) == {"a", "b"}

    def test_get_all_checks_defaults_to_time_checks_type(self, tmp_path):
        state = AutomationState(state_file=tmp_path / "state.json")
        state.set_last_run("a", 1.0, "time_checks")
        assert "a" in state.get_all_checks()
