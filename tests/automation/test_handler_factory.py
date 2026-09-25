"""Tests for src.automation.handler_factory.HandlerFactory.

Uses real, lightweight routine classes (HelpRoutine as a TimeCheckRoutine
subclass, DummyDailyRoutine as a non-TimeCheckRoutine subclass - see
tests/fixtures/dummy_daily_routine.py) rather than mocking importlib, so the
real dotted-path import machinery is actually exercised.
"""
import importlib as importlib_module
from types import SimpleNamespace

from src.automation.handler_factory import HandlerFactory
from src.automation.routines.help import HelpRoutine
from src.automation.routines.routineBase import TimeCheckRoutine

HELP_PATH = "src.automation.routines.help.HelpRoutine"
DUMMY_DAILY_PATH = "tests.fixtures.dummy_daily_routine.DummyDailyRoutine"


class TestTimeCheckRoutineBranch:
    def test_creates_handler_with_interval_from_config(self):
        factory = HandlerFactory()
        automation = SimpleNamespace(game_state={"is_home": True})
        handler = factory.create_handler(HELP_PATH, "device1", {"interval": 40}, automation=automation)
        assert isinstance(handler, HelpRoutine)
        assert isinstance(handler, TimeCheckRoutine)
        assert handler.interval == 40
        assert handler.automation is automation

    def test_accepts_time_to_check_as_alternate_interval_key(self):
        factory = HandlerFactory()
        handler = factory.create_handler(HELP_PATH, "device1", {"time_to_check": 25})
        assert handler.interval == 25

    def test_missing_interval_returns_none_and_marks_failed(self):
        factory = HandlerFactory()
        handler = factory.create_handler(HELP_PATH, "device1", {})
        assert handler is None
        assert HELP_PATH in factory.failed_handlers

    def test_zero_interval_treated_as_falsy_and_fails(self):
        factory = HandlerFactory()
        handler = factory.create_handler(HELP_PATH, "device1", {"interval": 0})
        assert handler is None
        assert HELP_PATH in factory.failed_handlers

    def test_hydrates_last_run_from_saved_last_check(self):
        """Regression test for bug #11: create_handler used to set a brand
        new, unused `handler.last_check` attribute instead of the field
        TimeCheckRoutine.should_run()/after_run() actually read/write
        (`_last_run`), so saved run-state hydration had zero effect."""
        factory = HandlerFactory()
        handler = factory.create_handler(HELP_PATH, "device1", {"interval": 60, "last_check": 12345.0})
        assert handler._last_run == 12345.0

    def test_no_last_check_in_config_leaves_default_last_run(self):
        factory = HandlerFactory()
        handler = factory.create_handler(HELP_PATH, "device1", {"interval": 60})
        assert handler._last_run == 0

    def test_excluded_keys_not_forwarded_to_constructor(self):
        # If "interval"/"last_check"/etc. leaked into **init_params, this
        # would raise TypeError (unexpected keyword argument) since
        # TimeCheckRoutine.__init__ takes interval positionally.
        factory = HandlerFactory()
        handler = factory.create_handler(
            HELP_PATH, "device1",
            {"handler": HELP_PATH, "interval": 60, "last_check": 1.0, "needs_check": True, "last_run": 2.0},
        )
        assert handler is not None
        assert handler.interval == 60


class TestNonTimeCheckRoutineBranch:
    def test_creates_handler_with_device_id_and_automation(self):
        factory = HandlerFactory()
        automation = SimpleNamespace(game_state={"is_home": True})
        handler = factory.create_handler(DUMMY_DAILY_PATH, "device1", {}, automation=automation)
        assert handler is not None
        assert not isinstance(handler, TimeCheckRoutine)
        assert handler.automation is automation
        assert handler.device_id == "device1"


class TestFailureHandling:
    def test_nonexistent_module_returns_none_and_marks_failed(self):
        factory = HandlerFactory()
        bad_path = "src.automation.routines.does_not_exist.NoSuchRoutine"
        handler = factory.create_handler(bad_path, "device1", {"interval": 60})
        assert handler is None
        assert bad_path in factory.failed_handlers

    def test_nonexistent_class_in_valid_module_returns_none_and_marks_failed(self):
        factory = HandlerFactory()
        bad_path = "src.automation.routines.help.NoSuchClass"
        handler = factory.create_handler(bad_path, "device1", {"interval": 60})
        assert handler is None
        assert bad_path in factory.failed_handlers

    def test_previously_failed_handler_short_circuits_without_reimporting(self, monkeypatch):
        factory = HandlerFactory()
        bad_path = "src.automation.routines.does_not_exist.NoSuchRoutine"

        # First call fails and caches the failure.
        assert factory.create_handler(bad_path, "device1", {"interval": 60}) is None
        assert bad_path in factory.failed_handlers

        real_import_module = importlib_module.import_module
        calls = []

        def counting_import_module(name, *args, **kwargs):
            calls.append(name)
            return real_import_module(name, *args, **kwargs)

        monkeypatch.setattr("src.automation.handler_factory.importlib.import_module", counting_import_module)

        # Second call for the same known-bad path should short-circuit
        # before ever attempting to import again.
        assert factory.create_handler(bad_path, "device1", {"interval": 60}) is None
        assert calls == []
