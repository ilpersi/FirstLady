"""Tests for HelpRoutine - the simplest TimeCheckRoutine, a single
find_and_tap_template call with no branching beyond that."""
from types import SimpleNamespace
from unittest.mock import patch

from src.automation.routines.help import HelpRoutine


def _make_routine(is_home=True):
    automation = SimpleNamespace(game_state={"is_home": is_home})
    return HelpRoutine("device1", interval=999, automation=automation), automation


class TestHelpRoutineExecute:
    def test_help_found_and_tapped_returns_true(self):
        routine, _ = _make_routine()
        with patch("src.automation.routines.help.find_and_tap_template", return_value=True) as mock_tap:
            assert routine._execute() is True
        mock_tap.assert_called_once()
        args, kwargs = mock_tap.call_args
        assert args[0] == "device1"
        assert args[1] == "help"

    def test_no_help_needed_also_returns_true(self):
        """find_and_tap_template returning False (no 'help' template on
        screen) is NOT treated as a failure here - both branches of
        _execute_internal return True. This is intentional, not a bug:
        "nothing to help with right now" is a normal, successful outcome for
        this routine, not an error."""
        routine, _ = _make_routine()
        with patch("src.automation.routines.help.find_and_tap_template", return_value=False) as mock_tap:
            assert routine._execute() is True
        mock_tap.assert_called_once()

    def test_exception_in_find_and_tap_template_is_caught_and_returns_false(self):
        """_execute_internal is wrapped via execute_with_error_handling, so
        an unexpected exception must not propagate."""
        routine, _ = _make_routine()
        with patch("src.automation.routines.help.find_and_tap_template", side_effect=RuntimeError("boom")):
            assert routine._execute() is False


class TestHelpRoutineStart:
    def test_start_when_already_home_runs_execute_without_navigating(self):
        routine, automation = _make_routine(is_home=True)
        with patch("src.automation.routines.help.find_and_tap_template", return_value=True), \
             patch("src.automation.routines.routineBase.navigate_home") as mock_nav:
            assert routine.start() is True
        mock_nav.assert_not_called()
        assert automation.game_state["is_home"] is True

    def test_start_when_not_home_navigates_first(self):
        routine, automation = _make_routine(is_home=False)
        with patch("src.automation.routines.help.find_and_tap_template", return_value=True), \
             patch("src.automation.routines.routineBase.navigate_home", return_value=True) as mock_nav:
            assert routine.start() is True
        mock_nav.assert_called_once_with("device1", True)
        assert automation.game_state["is_home"] is True

    def test_start_returns_false_when_navigation_fails(self):
        routine, automation = _make_routine(is_home=False)
        with patch("src.automation.routines.help.find_and_tap_template", return_value=True), \
             patch("src.automation.routines.routineBase.navigate_home", return_value=False):
            assert routine.start() is False
