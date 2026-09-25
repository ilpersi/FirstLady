"""Tests for src.automation.automation.MainAutomation."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.automation.automation import MainAutomation
from src.core.config import CONFIG


@pytest.fixture
def automation(isolated_repo_cwd):
    """A MainAutomation constructed with an empty automation.json (from
    isolated_repo_cwd) so no real device/config is touched, and setup_logging
    doesn't blow up."""
    return MainAutomation("device1")


class TestInitializeTimeChecks:
    def test_filters_out_null_interval_entries(self, automation):
        config = {
            "secretary": {"handler": "some.Handler", "interval": 40},
            "help": {"handler": "some.Other", "interval": None},
        }
        result = automation.initialize_time_checks(config)
        assert set(result.keys()) == {"secretary"}

    def test_kept_entries_have_expected_shape(self, automation):
        config = {"secretary": {"handler": "some.Handler", "interval": 40}}
        result = automation.initialize_time_checks(config)
        assert result["secretary"]["time_to_check"] == 40
        assert result["secretary"]["handler"] == "some.Handler"
        assert result["secretary"]["needs_check"] is True
        assert result["secretary"]["last_run"] is None

    def test_null_interval_never_reaches_update_interval_check(self, automation):
        """Confirms bug #10 from the plan is NOT an actual bug: null-interval
        entries are filtered here, before scheduling.update_interval_check
        (which does an unguarded `elapsed >= time_to_check` that would
        TypeError on a None interval) ever sees them."""
        from src.core.scheduling import update_interval_check

        config = {
            "secretary": {"handler": "some.Handler", "interval": 40},
            "help": {"handler": "some.Other", "interval": None},
        }
        checks = automation.initialize_time_checks(config)
        # Must not raise - proves no None interval leaked through.
        update_interval_check(checks, current_time=1000.0)


class TestInitializeScheduledEvents:
    def test_filters_out_null_day_entries(self, automation):
        """weekly_reset's `day: null` in the real config/automation.json is
        intentional (its handler module weeklyReset.py does not exist,
        commented out in routines/__init__.py) - not a bug to fix, just
        confirming it's correctly filtered out here."""
        config = {
            "weekly_reset": {"handler": "some.Weekly", "schedule": {"day": None, "time": "01:50"}},
        }
        result = automation.initialize_scheduled_events(config)
        assert result == {}

    def test_kept_entries_have_expected_shape(self, automation):
        config = {
            "weekly_reset": {"handler": "some.Weekly", "schedule": {"day": "friday", "time": "01:50"}},
        }
        result = automation.initialize_scheduled_events(config)
        assert result["weekly_reset"]["day"] == "friday"
        assert result["weekly_reset"]["time"] == "01:50"
        assert result["weekly_reset"]["handler"] == "some.Weekly"


class TestGetOrderedTasks:
    def test_scheduled_events_always_sort_before_time_checks(self, automation):
        automation.time_checks = {
            "secretary": {"needs_check": True, "last_run": 0, "time_to_check": 40},
        }
        automation.scheduled_events = {
            "weekly_reset": {"needs_check": True},
        }
        tasks = automation.get_ordered_tasks()
        names = [t[0] for t in tasks]
        assert names[0] == "weekly_reset"
        assert names[1] == "secretary"

    def test_time_checks_ordered_by_most_overdue_first(self, automation):
        automation.time_checks = {
            "barely_overdue": {"needs_check": True, "last_run": 990, "time_to_check": 60},
            "very_overdue": {"needs_check": True, "last_run": 0, "time_to_check": 60},
        }
        automation.scheduled_events = {}
        # overdue_time = now - (last_run + interval); "very_overdue" has a
        # far smaller last_run so it's always more overdue regardless of now.
        tasks = automation.get_ordered_tasks()
        names = [t[0] for t in tasks]
        assert names == ["very_overdue", "barely_overdue"]

    def test_needs_check_false_entries_excluded(self, automation):
        automation.time_checks = {
            "not_due": {"needs_check": False, "last_run": 0, "time_to_check": 60},
        }
        automation.scheduled_events = {}
        tasks = automation.get_ordered_tasks()
        assert tasks == []


class TestRunScheduledTasks:
    def test_happy_path_calls_start_and_after_run_and_saves_state(self, automation):
        handler = SimpleNamespace(
            should_run=lambda: True,
            start=lambda: True,
            after_run=lambda: None,
        )
        automation.time_checks = {
            "secretary": {"needs_check": True, "last_run": 0, "time_to_check": 40, "handler": "x.Handler"},
        }
        automation.scheduled_events = {}
        automation.handlers["x.Handler"] = handler

        automation.run_scheduled_tasks()

        assert automation.time_checks["secretary"]["needs_check"] is False
        assert automation.time_checks["secretary"]["last_run"] > 0

    def test_should_run_false_skips_handler_entirely(self, automation):
        calls = {"start": 0}
        handler = SimpleNamespace(
            should_run=lambda: False,
            start=lambda: calls.__setitem__("start", calls["start"] + 1) or True,
            after_run=lambda: None,
        )
        automation.time_checks = {
            "secretary": {"needs_check": True, "last_run": 0, "time_to_check": 40, "handler": "x.Handler"},
        }
        automation.scheduled_events = {}
        automation.handlers["x.Handler"] = handler

        automation.run_scheduled_tasks()

        assert calls["start"] == 0

    def test_failure_triggers_one_reset_and_retry_then_succeeds(self, automation, monkeypatch):
        start_calls = []
        handler = SimpleNamespace(
            should_run=lambda: True,
            start=lambda: (start_calls.append(1), False if len(start_calls) == 1 else True)[1],
            after_run=lambda: None,
        )
        automation.time_checks = {
            "secretary": {"needs_check": True, "last_run": 0, "time_to_check": 40, "handler": "x.Handler"},
        }
        automation.scheduled_events = {}
        automation.handlers["x.Handler"] = handler

        reset_calls = []
        monkeypatch.setattr(automation, "reset_game", lambda: (reset_calls.append(1), True)[1])

        automation.run_scheduled_tasks()

        assert len(start_calls) == 2
        assert len(reset_calls) == 1
        assert automation.time_checks["secretary"]["needs_check"] is False
        assert automation.time_checks["secretary"]["last_run"] > 0

    def test_failure_then_reset_failure_gives_up(self, automation, monkeypatch):
        start_calls = []
        handler = SimpleNamespace(
            should_run=lambda: True,
            start=lambda: start_calls.append(1) or False,
            after_run=lambda: None,
        )
        automation.time_checks = {
            "secretary": {"needs_check": True, "last_run": 0, "time_to_check": 40, "handler": "x.Handler"},
        }
        automation.scheduled_events = {}
        automation.handlers["x.Handler"] = handler
        monkeypatch.setattr(automation, "reset_game", lambda: False)

        automation.run_scheduled_tasks()

        assert len(start_calls) == 1
        assert automation.time_checks["secretary"]["needs_check"] is False
        # last_run must NOT be updated on a give-up path.
        assert automation.time_checks["secretary"]["last_run"] == 0

    def test_missing_handler_is_skipped_without_error(self, automation):
        automation.time_checks = {
            "secretary": {"needs_check": True, "last_run": 0, "time_to_check": 40, "handler": "x.Handler"},
        }
        automation.scheduled_events = {}
        # No entry pre-populated in automation.handlers and the real
        # handler_factory will fail to import "x.Handler" -> get_handler
        # returns None -> the loop must skip it without raising.
        automation.run_scheduled_tasks()


class TestVerifyGameRunning:
    def test_returns_true_immediately_when_game_already_running(self, automation, monkeypatch):
        monkeypatch.setattr("src.automation.automation.verify_emulator_running", lambda: True)
        monkeypatch.setattr("src.automation.automation.enforce_connection", lambda: None)
        CONFIG._config["package_name"] = "com.fun.lastwar.gp"
        monkeypatch.setattr(
            "src.automation.automation.get_current_running_app",
            lambda device_id: "com.fun.lastwar.gp",
        )

        assert automation.verify_game_running() is True

    def test_sends_single_content_string_notification_on_10_minute_cap(self, automation, monkeypatch):
        """Regression test for bug #13: verify_game_running used to call
        send_notification(content, embeds_string) with a plain string as the
        `embeds` positional arg - discord.py can't serialize a string as an
        Embed, so this alert silently never worked. After the fix, both
        pieces are combined into a single positional `content` string."""
        monkeypatch.setattr("src.automation.automation.verify_emulator_running", lambda: True)
        monkeypatch.setattr("src.automation.automation.enforce_connection", lambda: None)
        monkeypatch.setattr(
            "src.automation.automation.get_current_running_app",
            lambda device_id: "some.other.app",
        )
        monkeypatch.setattr("src.automation.automation.launch_game", lambda device_id: False)
        CONFIG._config["package_name"] = "com.fun.lastwar.gp"
        CONFIG._config.setdefault("timings", {})["home_check_interval"] = 600
        CONFIG._config["max_home_attempts"] = 100

        monkeypatch.setenv("AUTOMATION_WEBHOOK_URL", "https://example.invalid/webhook")
        monkeypatch.setattr("src.automation.automation.time.time", lambda: 999999.0)

        send_notification_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "src.core.discord_bot.DiscordNotifier.send_notification", send_notification_mock
        )

        sleep_calls = {"count": 0}

        def fake_sleep(seconds):
            sleep_calls["count"] += 1
            if sleep_calls["count"] == 1:
                raise RuntimeError("stop the infinite loop after first notification")

        monkeypatch.setattr("src.automation.automation.time.sleep", fake_sleep)

        result = automation.verify_game_running()

        assert result is False  # the forced RuntimeError is caught by verify_game_running's own except
        send_notification_mock.assert_called_once()
        call_args = send_notification_mock.call_args
        # AsyncMock is not a descriptor, so patching it directly onto the
        # class means attribute access via the instance does NOT bind
        # `self` - call_args.args is exactly what verify_game_running
        # passed as positional arguments to discord.send_notification(...).
        assert len(call_args.args) == 1
        assert "Game Launch Failed" in call_args.args[0]
        assert "Retry count" in call_args.args[0]

    def test_exception_is_caught_and_returns_false(self, automation, monkeypatch):
        def raise_error():
            raise RuntimeError("boom")

        monkeypatch.setattr("src.automation.automation.verify_emulator_running", raise_error)
        monkeypatch.setattr("src.automation.automation.time.sleep", lambda s: None)

        assert automation.verify_game_running() is False
