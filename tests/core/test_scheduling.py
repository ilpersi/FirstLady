"""Pure-logic tests for src.core.scheduling - no I/O, no CONFIG dependency."""
from datetime import datetime, timezone

from src.core.scheduling import update_interval_check, update_schedule


def _ts(*, year=2024, month=1, day=1, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).timestamp()


class TestUpdateIntervalCheck:
    def test_first_run_is_always_due(self):
        checks = {"foo": {"last_run": None, "needs_check": False, "time_to_check": 60}}
        result = update_interval_check(checks, current_time=1000.0)
        assert result["foo"]["needs_check"] is True

    def test_not_yet_due(self):
        checks = {"foo": {"last_run": 1000.0, "needs_check": False, "time_to_check": 60}}
        result = update_interval_check(checks, current_time=1030.0)
        assert result["foo"]["needs_check"] is False

    def test_boundary_elapsed_equals_interval_is_due(self):
        checks = {"foo": {"last_run": 1000.0, "needs_check": False, "time_to_check": 60}}
        result = update_interval_check(checks, current_time=1060.0)
        assert result["foo"]["needs_check"] is True

    def test_elapsed_beyond_interval_is_due(self):
        checks = {"foo": {"last_run": 1000.0, "needs_check": False, "time_to_check": 60}}
        result = update_interval_check(checks, current_time=1200.0)
        assert result["foo"]["needs_check"] is True

    def test_mutates_in_place_and_returns_same_object(self):
        checks = {"foo": {"last_run": None, "needs_check": False, "time_to_check": 60}}
        result = update_interval_check(checks, current_time=1000.0)
        assert result is checks

    def test_multiple_checks_independent(self):
        checks = {
            "due": {"last_run": 0.0, "needs_check": False, "time_to_check": 60},
            "not_due": {"last_run": 990.0, "needs_check": False, "time_to_check": 60},
        }
        result = update_interval_check(checks, current_time=1000.0)
        assert result["due"]["needs_check"] is True
        assert result["not_due"]["needs_check"] is False


class TestUpdateSchedule:
    def test_day_mismatch_never_marked_due(self):
        # 2024-01-01 is a Monday.
        current_time = _ts(hour=13, minute=50)
        events = {"e": {"last_check": None, "needs_check": False, "day": "tuesday", "time": "13:50"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is False

    def test_within_window_on_matching_day_marks_due(self):
        current_time = _ts(hour=13, minute=52)  # Monday
        events = {"e": {"last_check": None, "needs_check": False, "day": "monday", "time": "13:50"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is True

    def test_outside_window_on_matching_day_not_due(self):
        current_time = _ts(hour=13, minute=57)  # 7 minutes past 13:50
        events = {"e": {"last_check": None, "needs_check": False, "day": "monday", "time": "13:50"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is False

    def test_already_ran_today_utc_is_skipped(self):
        current_time = _ts(hour=13, minute=51)
        last_check = _ts(hour=13, minute=50)  # same UTC date
        events = {"e": {"last_check": last_check, "needs_check": False, "day": "monday", "time": "13:50"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is False

    def test_ran_on_a_previous_day_is_eligible_again(self):
        current_time = _ts(day=8, hour=13, minute=51)  # next Monday
        last_check = _ts(day=1, hour=13, minute=50)
        events = {"e": {"last_check": last_check, "needs_check": False, "day": "monday", "time": "13:50"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is True

    def test_day_is_none_never_scheduled(self):
        current_time = _ts(hour=13, minute=50)
        events = {"e": {"last_check": None, "needs_check": False, "day": None, "time": "13:50"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is False

    def test_day_match_is_case_insensitive(self):
        current_time = _ts(hour=13, minute=50)  # Monday
        events = {"e": {"last_check": None, "needs_check": False, "day": "MONDAY", "time": "13:50"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is True

    def test_midnight_wraparound_just_before_midnight(self):
        """current=23:59, target=00:02 on the same calendar date -> ~3
        minutes apart once wraparound is accounted for. Before the fix this
        computed ~1437 minutes and never fired."""
        current_time = _ts(day=1, hour=23, minute=59)  # Monday 23:59 UTC
        events = {"e": {"last_check": None, "needs_check": False, "day": "monday", "time": "00:02"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is True

    def test_midnight_wraparound_just_after_midnight(self):
        current_time = _ts(day=1, hour=0, minute=2)  # Monday 00:02 UTC
        events = {"e": {"last_check": None, "needs_check": False, "day": "monday", "time": "23:59"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is True

    def test_far_from_midnight_unaffected_by_wraparound_fix(self):
        current_time = _ts(hour=12, minute=0)  # Monday noon
        events = {"e": {"last_check": None, "needs_check": False, "day": "monday", "time": "13:50"}}
        result = update_schedule(events, current_time)
        assert result["e"]["needs_check"] is False
