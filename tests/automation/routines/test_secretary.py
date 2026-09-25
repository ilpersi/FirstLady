"""Tests for SecretaryRoutine - the fullest integration test in the suite.

All ADB/image/OCR/controls calls are mocked at the boundary secretary.py
itself imports them at (e.g. `src.automation.routines.secretary.find_template`),
since every dependency is imported by name directly into that module's
namespace rather than accessed through a module reference.

Important: `CONTROL_LIST` is imported the same way (`from
src.core.text_detection import ... CONTROL_LIST`), so it is a frozen
snapshot of `CONFIG.control_list` taken once at import time - NOT the live
`CONFIG` object. Tests that need whitelist/blacklist contents must patch
`src.automation.routines.secretary.CONTROL_LIST` directly; mutating
`CONFIG._control_list` has no effect on it.
"""
import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from src.automation.routines.secretary import SecretaryRoutine

SECRETARY_MODULE = "src.automation.routines.secretary"
DUMMY_SCREENSHOT = np.zeros((10, 10, 3), dtype=np.uint8)


def _make_routine(is_home=True):
    automation = SimpleNamespace(game_state={"is_home": is_home})
    routine = SecretaryRoutine("device1", interval=999, automation=automation)
    return routine, automation


def _by_template(mapping, default=None):
    """Build a side_effect fn for find_template/find_and_tap_template/
    find_all_templates that dispatches on the template_name (2nd positional
    arg), regardless of what else is passed (existing_screenshot, timeout,
    error_msg, etc.)."""

    def _fn(device_id, template_name, *args, **kwargs):
        if template_name in mapping:
            value = mapping[template_name]
            if callable(value):
                return value()
            return value
        return default

    return _fn


def _sequence(*values):
    """Return a callable that yields successive values from `values` on each
    call, repeating the last one once exhausted."""
    it = iter(values)
    last = {"v": None}

    def _next():
        try:
            last["v"] = next(it)
        except StopIteration:
            pass
        return last["v"]

    return _next


@pytest.fixture(autouse=True)
def no_delay():
    """human_delay would otherwise really sleep (CONFIG timings are real
    seconds) - every secretary test patches it out."""
    with patch(f"{SECRETARY_MODULE}.human_delay"):
        yield


@pytest.fixture
def president_found():
    """exit_to_secretary_menu's first check (verify_secretary_menu) must
    succeed so tests don't fall through to a real press_back loop."""
    with patch(f"{SECRETARY_MODULE}.wait_for_image", side_effect=_by_template({"president": (5, 5)})):
        yield


class TestProcessSecretaryPositionAlreadyFull:
    def test_full_list_short_circuits_before_list_button(self, president_found):
        routine, _ = _make_routine()
        tap_calls = []

        def record_tap(device_id, name, **kwargs):
            tap_calls.append(name)
            return True

        with patch(f"{SECRETARY_MODULE}.find_and_tap_template", side_effect=record_tap), \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"full_list": (1, 1)})):
            assert routine.process_secretary_position("strategy") is True

        assert tap_calls == ["strategy"]  # "list" is never reached


class TestProcessSecretaryPositionListButtonMissing:
    def test_list_button_not_found_returns_false(self, president_found):
        routine, _ = _make_routine()
        with patch(f"{SECRETARY_MODULE}.find_and_tap_template", side_effect=_by_template({"strategy": True, "list": False})), \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"full_list": None})):
            assert routine.process_secretary_position("strategy") is False


class TestProcessSecretaryPositionWhitelist:
    def test_whitelisted_alliance_is_accepted(self, president_found):
        routine, _ = _make_routine()
        accept_seq = _sequence([(50, 60)], [(50, 60)], [])

        with patch(f"{SECRETARY_MODULE}.CONTROL_LIST", {"whitelist": {"alliance": ["ABC"]}, "blacklist": {"alliance": []}}), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", side_effect=_by_template({"strategy": True, "list": True})), \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"full_list": None})), \
             patch(f"{SECRETARY_MODULE}.find_all_templates", side_effect=_by_template({"accept": accept_seq}, default=[])), \
             patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.get_text_regions", return_value=((0, 0, 5, 5), (5, 0, 10, 5), DUMMY_SCREENSHOT)), \
             patch(f"{SECRETARY_MODULE}.extract_text_from_region", return_value=("ABC", "ABC")), \
             patch(f"{SECRETARY_MODULE}.log_rejected_alliance") as mock_log, \
             patch(f"{SECRETARY_MODULE}.humanized_tap") as mock_tap:
            assert routine.process_secretary_position("strategy") is True

        mock_tap.assert_called_once_with("device1", 50, 60)
        mock_log.assert_not_called()

    def test_non_whitelisted_alliance_rejected_via_reject_button(self, president_found):
        routine, _ = _make_routine()
        accept_seq = _sequence([(50, 60)], [(50, 60)], [])

        with patch(f"{SECRETARY_MODULE}.CONTROL_LIST", {"whitelist": {"alliance": ["ABC"]}, "blacklist": {"alliance": []}}), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", side_effect=_by_template({"strategy": True, "list": True, "confirm": True})) as mock_fat, \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"full_list": None})), \
             patch(f"{SECRETARY_MODULE}.find_all_templates", side_effect=_by_template({"accept": accept_seq, "reject": [(52, 60)]})), \
             patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.get_text_regions", return_value=((0, 0, 5, 5), (5, 0, 10, 5), DUMMY_SCREENSHOT)), \
             patch(f"{SECRETARY_MODULE}.extract_text_from_region", return_value=("XYZ", "XYZ-original")), \
             patch(f"{SECRETARY_MODULE}.log_rejected_alliance") as mock_log, \
             patch(f"{SECRETARY_MODULE}.humanized_tap") as mock_tap:
            assert routine.process_secretary_position("strategy") is True

        mock_log.assert_called_once_with("XYZ", "XYZ-original")
        mock_tap.assert_called_once_with("device1", 52, 60)  # taps the reject button, not accept
        assert "confirm" in [c.args[1] for c in mock_fat.call_args_list]

    def test_non_whitelisted_alliance_rejected_via_confirm_fallback_when_no_reject_button(self, president_found):
        routine, _ = _make_routine()
        accept_seq = _sequence([(50, 60)], [(50, 60)], [])

        with patch(f"{SECRETARY_MODULE}.CONTROL_LIST", {"whitelist": {"alliance": ["ABC"]}, "blacklist": {"alliance": []}}), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", side_effect=_by_template({"strategy": True, "list": True, "confirm": True})) as mock_fat, \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"full_list": None})), \
             patch(f"{SECRETARY_MODULE}.find_all_templates", side_effect=_by_template({"accept": accept_seq, "reject": []})), \
             patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.get_text_regions", return_value=((0, 0, 5, 5), (5, 0, 10, 5), DUMMY_SCREENSHOT)), \
             patch(f"{SECRETARY_MODULE}.extract_text_from_region", return_value=("XYZ", "XYZ-original")), \
             patch(f"{SECRETARY_MODULE}.log_rejected_alliance"), \
             patch(f"{SECRETARY_MODULE}.humanized_tap") as mock_tap:
            assert routine.process_secretary_position("strategy") is True

        mock_tap.assert_not_called()  # no reject button and no whitelist tap either
        assert "confirm" in [c.args[1] for c in mock_fat.call_args_list]
        assert routine.last_approve["strategy"] is not None

    def test_empty_whitelist_accepts_all_without_ocr(self, president_found):
        routine, _ = _make_routine()
        accept_seq = _sequence([(70, 80)], [(70, 80)], [])

        with patch(f"{SECRETARY_MODULE}.CONTROL_LIST", {"whitelist": {"alliance": []}, "blacklist": {"alliance": []}}), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", side_effect=_by_template({"strategy": True, "list": True})), \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"full_list": None})), \
             patch(f"{SECRETARY_MODULE}.find_all_templates", side_effect=_by_template({"accept": accept_seq})), \
             patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.get_text_regions") as mock_regions, \
             patch(f"{SECRETARY_MODULE}.extract_text_from_region") as mock_ocr, \
             patch(f"{SECRETARY_MODULE}.humanized_tap") as mock_tap:
            assert routine.process_secretary_position("strategy") is True

        mock_regions.assert_not_called()
        mock_ocr.assert_not_called()
        mock_tap.assert_called_once_with("device1", 70, 80)


class TestFindPositionsWithApplicants:
    def test_matches_position_within_applicant_offset(self):
        routine, _ = _make_routine()
        with patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_all_templates", side_effect=_by_template(
                 {"development": [(100, 100)], "has_applicant": [(200, 120)]}, default=[])):
            result = routine.find_positions_with_applicants()
        assert result == ["development"]

    def test_applicant_too_far_is_not_matched(self):
        routine, _ = _make_routine()
        with patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_all_templates", side_effect=_by_template(
                 {"development": [(100, 100)], "has_applicant": [(500, 500)]}, default=[])):
            result = routine.find_positions_with_applicants()
        assert result == []

    def test_no_applicant_icons_returns_empty(self):
        routine, _ = _make_routine()
        with patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_all_templates", side_effect=_by_template({"has_applicant": []}, default=[])):
            result = routine.find_positions_with_applicants()
        assert result == []


class TestFindPositionsToRemove:
    def test_no_auto_remove_config_returns_empty(self):
        from src.core.config import CONFIG
        routine, _ = _make_routine()
        original = CONFIG._config.get("auto_remove")
        CONFIG._config = {k: v for k, v in CONFIG._config.items() if k != "auto_remove"}
        try:
            assert routine.find_positions_to_remove() == []
        finally:
            if original is not None:
                CONFIG._config["auto_remove"] = original

    def test_position_past_delay_and_not_vacant_is_flagged(self):
        routine, _ = _make_routine()
        routine.last_approve["strategy"] = dt.datetime.now() - dt.timedelta(seconds=700)  # > 600s configured
        with patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template(
                 {"vacant-strategy": None, "strategy": (1, 1)}, default=None)):
            result = routine.find_positions_to_remove()
        assert "strategy" in result

    def test_vacant_position_resets_timer_and_is_not_flagged(self):
        routine, _ = _make_routine()
        routine.last_approve["strategy"] = dt.datetime.now() - dt.timedelta(seconds=700)
        with patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"vacant-strategy": (1, 1)}, default=None)):
            result = routine.find_positions_to_remove()
        assert "strategy" not in result
        assert routine.last_approve["strategy"] > dt.datetime.now() - dt.timedelta(seconds=5)

    def test_timer_not_yet_elapsed_is_skipped(self):
        routine, _ = _make_routine()
        routine.last_approve["strategy"] = dt.datetime.now()  # just approved, well under 600s
        with patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_template") as mock_find:
            result = routine.find_positions_to_remove()
        assert result == []
        mock_find.assert_not_called()

    def test_position_with_no_configured_delay_is_skipped(self):
        routine, _ = _make_routine()
        routine.last_approve["development"] = dt.datetime.now() - dt.timedelta(seconds=10000)
        with patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_template") as mock_find:
            result = routine.find_positions_to_remove()
        # "development"'s title_cfg entry is null in the real config, so it's
        # always skipped regardless of elapsed time.
        assert "development" not in result


class TestProcessRemovePosition:
    def test_still_queued_updates_timer_without_dismissing(self, president_found):
        routine, _ = _make_routine()
        before = routine.last_approve["strategy"]
        with patch(f"{SECRETARY_MODULE}.find_and_tap_template", side_effect=_by_template({"strategy": True})) as mock_fat, \
             patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"empty_list": None})):
            assert routine.process_remove_position("strategy") is True
        assert routine.last_approve["strategy"] > before
        assert "dismiss" not in [c.args[1] for c in mock_fat.call_args_list]

    def test_appoint_found_dismisses_and_confirms(self, president_found):
        routine, _ = _make_routine()
        with patch(f"{SECRETARY_MODULE}.find_and_tap_template", side_effect=_by_template(
                {"strategy": True, "dismiss": True, "confirm-blue": True})) as mock_fat, \
             patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"empty_list": (1, 1), "appoint": (1, 1)})):
            assert routine.process_remove_position("strategy") is True
        called_names = [c.args[1] for c in mock_fat.call_args_list]
        assert "dismiss" in called_names and "confirm-blue" in called_names

    def test_no_appoint_means_timer_not_over(self, president_found):
        routine, _ = _make_routine()
        before = routine.last_approve["strategy"]
        with patch(f"{SECRETARY_MODULE}.find_and_tap_template", side_effect=_by_template({"strategy": True})) as mock_fat, \
             patch(f"{SECRETARY_MODULE}._take_and_load_screenshot", return_value=DUMMY_SCREENSHOT), \
             patch(f"{SECRETARY_MODULE}.find_template", side_effect=_by_template({"empty_list": (1, 1), "appoint": None})):
            assert routine.process_remove_position("strategy") is True
        assert routine.last_approve["strategy"] > before
        assert "dismiss" not in [c.args[1] for c in mock_fat.call_args_list]


class TestProcessAllAutoRemovePositions:
    def test_processes_every_flagged_position(self):
        routine, _ = _make_routine()
        with patch.object(routine, "find_positions_to_remove", return_value=["strategy", "security"]), \
             patch.object(routine, "process_remove_position", return_value=True) as mock_process:
            assert routine.process_all_auto_remove_positions() is True
        assert mock_process.call_args_list == [(("strategy",),), (("security",),)]

    def test_stops_on_first_failure(self):
        routine, _ = _make_routine()
        with patch.object(routine, "find_positions_to_remove", return_value=["strategy", "security"]), \
             patch.object(routine, "process_remove_position", return_value=False) as mock_process:
            assert routine.process_all_auto_remove_positions() is False
        mock_process.assert_called_once_with("strategy")

    def test_no_positions_to_remove_returns_true(self):
        routine, _ = _make_routine()
        with patch.object(routine, "find_positions_to_remove", return_value=[]):
            assert routine.process_all_auto_remove_positions() is True


class TestProcessAllSecretaryPositions:
    def test_no_applicants_and_menu_still_accessible_returns_true(self):
        routine, _ = _make_routine()
        with patch.object(routine, "find_positions_with_applicants", return_value=[]), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", return_value=True), \
             patch(f"{SECRETARY_MODULE}.find_template", return_value=(1, 1)):
            assert routine.process_all_secretary_positions() is True

    def test_no_applicants_and_menu_not_accessible_raises(self):
        routine, _ = _make_routine()
        with patch.object(routine, "find_positions_with_applicants", return_value=[]), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", return_value=False):
            with pytest.raises(RuntimeError, match="secretary not accessible"):
                routine.process_all_secretary_positions()

    def test_no_applicants_tap_ok_but_list_missing_raises(self):
        routine, _ = _make_routine()
        with patch.object(routine, "find_positions_with_applicants", return_value=[]), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", return_value=True), \
             patch(f"{SECRETARY_MODULE}.find_template", return_value=None):
            with pytest.raises(RuntimeError, match="secretary not accessible"):
                routine.process_all_secretary_positions()

    def test_delegates_to_process_secretary_position_per_match(self):
        routine, _ = _make_routine()
        with patch.object(routine, "find_positions_with_applicants", return_value=["strategy", "security"]), \
             patch.object(routine, "process_secretary_position", return_value=True) as mock_process:
            assert routine.process_all_secretary_positions() is True
        assert [c.args[0] for c in mock_process.call_args_list] == ["strategy", "security"]

    def test_stops_on_first_position_failure(self):
        routine, _ = _make_routine()
        with patch.object(routine, "find_positions_with_applicants", return_value=["strategy", "security"]), \
             patch.object(routine, "process_secretary_position", return_value=False) as mock_process:
            assert routine.process_all_secretary_positions() is False
        mock_process.assert_called_once_with("strategy")


class TestExecuteInternal:
    def test_capitol_menu_missing_returns_false(self):
        routine, automation = _make_routine()
        with patch.object(routine, "open_profile_menu", return_value=True), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", return_value=False), \
             patch.object(routine, "process_all_auto_remove_positions") as mock_remove, \
             patch.object(routine, "process_all_secretary_positions") as mock_positions:
            assert routine._execute_internal() is False
        assert automation.game_state["is_home"] is False
        mock_remove.assert_not_called()
        mock_positions.assert_not_called()

    def test_happy_path_runs_auto_remove_then_positions(self):
        routine, _ = _make_routine()
        with patch.object(routine, "open_profile_menu", return_value=True), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", return_value=True), \
             patch(f"{SECRETARY_MODULE}.handle_swipes"), \
             patch.object(routine, "process_all_auto_remove_positions", return_value=True) as mock_remove, \
             patch.object(routine, "process_all_secretary_positions", return_value=True) as mock_positions:
            assert routine._execute_internal() is True
        mock_remove.assert_called_once()
        mock_positions.assert_called_once()

    def test_auto_remove_skipped_when_inactive_in_config(self):
        from src.core.config import CONFIG
        routine, _ = _make_routine()
        CONFIG._config["auto_remove"] = {"active": False, "title_cfg": {}}
        with patch.object(routine, "open_profile_menu", return_value=True), \
             patch(f"{SECRETARY_MODULE}.find_and_tap_template", return_value=True), \
             patch(f"{SECRETARY_MODULE}.handle_swipes"), \
             patch.object(routine, "process_all_auto_remove_positions") as mock_remove, \
             patch.object(routine, "process_all_secretary_positions", return_value=True):
            assert routine._execute_internal() is True
        mock_remove.assert_not_called()
