"""Tests for src.automation.routines.routineBase (RoutineBase, TimeCheckRoutine,
DailyRoutine)."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.automation.handler_factory import HandlerFactory
from src.automation.routines.routineBase import RoutineBase, TimeCheckRoutine
from tests.fixtures.dummy_daily_routine import DummyDailyRoutine

DUMMY_DAILY_PATH = "tests.fixtures.dummy_daily_routine.DummyDailyRoutine"


class _StubRoutine(RoutineBase):
    """Minimal concrete RoutineBase for testing start()/execute_with_error_handling()."""

    def __init__(self, device_id, automation=None, execute_result=True, execute_raises=None):
        super().__init__(device_id, automation)
        self.execute_result = execute_result
        self.execute_raises = execute_raises
        self.execute_called = False

    def _execute(self):
        self.execute_called = True
        if self.execute_raises:
            raise self.execute_raises
        return self.execute_result

    def should_run(self):
        return True

    def after_run(self):
        pass


class TestRoutineBaseStart:
    def test_already_home_calls_execute_without_navigating(self, monkeypatch):
        called = {"navigate_home": False}
        monkeypatch.setattr(
            "src.automation.routines.routineBase.navigate_home",
            lambda *a, **k: called.__setitem__("navigate_home", True) or True,
        )
        automation = SimpleNamespace(game_state={"is_home": True})
        routine = _StubRoutine("device1", automation=automation)

        result = routine.start()

        assert result is True
        assert routine.execute_called is True
        assert called["navigate_home"] is False

    def test_not_home_navigates_then_executes(self, monkeypatch):
        navigate_calls = []

        def fake_navigate_home(device_id, force):
            navigate_calls.append((device_id, force))
            return True

        monkeypatch.setattr("src.automation.routines.routineBase.navigate_home", fake_navigate_home)
        automation = SimpleNamespace(game_state={"is_home": False})
        routine = _StubRoutine("device1", automation=automation)

        result = routine.start()

        assert result is True
        assert navigate_calls == [("device1", True)]
        assert automation.game_state["is_home"] is True
        assert routine.execute_called is True

    def test_navigate_home_failure_returns_false_without_executing(self, monkeypatch):
        monkeypatch.setattr("src.automation.routines.routineBase.navigate_home", lambda *a, **k: False)
        automation = SimpleNamespace(game_state={"is_home": False})
        routine = _StubRoutine("device1", automation=automation)

        result = routine.start()

        assert result is False
        assert routine.execute_called is False

    def test_exception_anywhere_is_caught_and_returns_false(self, monkeypatch):
        monkeypatch.setattr("src.automation.routines.routineBase.navigate_home", lambda *a, **k: True)
        automation = SimpleNamespace(game_state={"is_home": False})
        routine = _StubRoutine("device1", automation=automation, execute_raises=RuntimeError("boom"))

        result = routine.start()

        assert result is False

    def test_automation_none_raises_internally_but_is_caught(self):
        # start() dereferences self.automation.game_state without a None
        # guard - with automation=None this raises AttributeError, which
        # start()'s own broad except must catch, returning False rather
        # than propagating.
        routine = _StubRoutine("device1", automation=None)
        assert routine.start() is False


class TestExecuteWithErrorHandling:
    def test_successful_call_returns_its_result(self):
        automation = SimpleNamespace(game_state={"is_home": True})
        routine = _StubRoutine("device1", automation=automation)

        result = routine.execute_with_error_handling(lambda: "ok")
        assert result == "ok"

    def test_raising_function_is_caught_and_returns_false(self):
        automation = SimpleNamespace(game_state={"is_home": True})
        routine = _StubRoutine("device1", automation=automation)

        def boom():
            raise ValueError("nope")

        assert routine.execute_with_error_handling(boom) is False

    def test_args_and_kwargs_are_forwarded(self):
        automation = SimpleNamespace(game_state={"is_home": True})
        routine = _StubRoutine("device1", automation=automation)

        def add(a, b, c=0):
            return a + b + c

        assert routine.execute_with_error_handling(add, 1, 2, c=3) == 6


class _ConcreteTimeCheckRoutine(TimeCheckRoutine):
    def _execute(self):
        return True


class TestTimeCheckRoutine:
    def test_last_run_none_after_manual_reset_always_due(self, monkeypatch):
        # __init__'s `last_run or 0` means _last_run can never naturally be
        # None post-construction; the `if self._last_run is None` branch is
        # still reachable if something sets it back to None directly.
        routine = _ConcreteTimeCheckRoutine("device1", interval=60)
        routine._last_run = None
        assert routine.should_run() is True

    def test_default_last_run_of_zero_is_immediately_due(self, monkeypatch):
        monkeypatch.setattr("src.automation.routines.routineBase.time.time", lambda: 1000.0)
        routine = _ConcreteTimeCheckRoutine("device1", interval=60)
        assert routine.should_run() is True

    def test_not_yet_due(self, monkeypatch):
        routine = _ConcreteTimeCheckRoutine("device1", interval=60, last_run=1000.0)
        monkeypatch.setattr("src.automation.routines.routineBase.time.time", lambda: 1030.0)
        assert routine.should_run() is False

    def test_due_at_boundary(self, monkeypatch):
        routine = _ConcreteTimeCheckRoutine("device1", interval=60, last_run=1000.0)
        monkeypatch.setattr("src.automation.routines.routineBase.time.time", lambda: 1060.0)
        assert routine.should_run() is True

    def test_after_run_updates_last_run_to_now(self, monkeypatch):
        monkeypatch.setattr("src.automation.routines.routineBase.time.time", lambda: 5000.0)
        routine = _ConcreteTimeCheckRoutine("device1", interval=60, last_run=1.0)
        routine.after_run()
        assert routine._last_run == 5000.0


class TestDailyRoutine:
    def test_automation_is_passed_through(self):
        """Regression test for bug #12: DailyRoutine.__init__ used to have
        no `automation` parameter at all and called super().__init__(device_id)
        with no automation, leaving self.automation permanently None."""
        automation = SimpleNamespace(game_state={"is_home": True})
        routine = DummyDailyRoutine("device1", day="monday", time="12:00", automation=automation)
        assert routine.automation is automation

    def test_defaults_automation_to_none_when_not_provided(self):
        routine = DummyDailyRoutine("device1", day="monday", time="12:00")
        assert routine.automation is None

    def test_start_reaches_execute_when_already_home(self):
        """Companion regression test: before the bug #12 fix, start() would
        always AttributeError on None.game_state and swallow it, returning
        False without ever reaching _execute()."""
        automation = SimpleNamespace(game_state={"is_home": True})
        factory = HandlerFactory()
        handler = factory.create_handler(DUMMY_DAILY_PATH, "device1", {}, automation=automation)

        result = handler.start()

        assert result is True
        assert handler.executed is True

    def _dt_timestamp(self, *, day=1, hour=0, minute=0):
        return datetime(2024, 1, day, hour, minute, tzinfo=timezone.utc).timestamp()

    def test_should_run_true_on_matching_day_and_time_window(self, monkeypatch):
        # 2024-01-01 is a Monday.
        routine = DummyDailyRoutine("device1", day="monday", time="13:50")
        monkeypatch.setattr(
            "src.automation.routines.routineBase.time.time",
            lambda: self._dt_timestamp(hour=13, minute=52),
        )
        assert routine.should_run() is True

    def test_should_run_false_on_wrong_day(self, monkeypatch):
        routine = DummyDailyRoutine("device1", day="tuesday", time="13:50")
        monkeypatch.setattr(
            "src.automation.routines.routineBase.time.time",
            lambda: self._dt_timestamp(hour=13, minute=50),
        )
        assert routine.should_run() is False

    def test_should_run_false_outside_time_window(self, monkeypatch):
        routine = DummyDailyRoutine("device1", day="monday", time="13:50")
        monkeypatch.setattr(
            "src.automation.routines.routineBase.time.time",
            lambda: self._dt_timestamp(hour=14, minute=10),
        )
        assert routine.should_run() is False

    def test_should_run_false_if_already_ran_today(self, monkeypatch):
        routine = DummyDailyRoutine("device1", day="monday", time="13:50")
        routine.last_run = self._dt_timestamp(hour=13, minute=50)
        monkeypatch.setattr(
            "src.automation.routines.routineBase.time.time",
            lambda: self._dt_timestamp(hour=13, minute=52),
        )
        assert routine.should_run() is False

    def test_should_run_true_if_ran_on_a_previous_day(self, monkeypatch):
        routine = DummyDailyRoutine("device1", day="monday", time="13:50")
        routine.last_run = self._dt_timestamp(day=1, hour=13, minute=50)
        monkeypatch.setattr(
            "src.automation.routines.routineBase.time.time",
            lambda: self._dt_timestamp(day=8, hour=13, minute=52),
        )
        assert routine.should_run() is True

    def test_after_run_sets_last_run_to_now(self, monkeypatch):
        monkeypatch.setattr("src.automation.routines.routineBase.time.time", lambda: 9999.0)
        routine = DummyDailyRoutine("device1", day="monday", time="13:50")
        routine.after_run()
        assert routine.last_run == 9999.0
