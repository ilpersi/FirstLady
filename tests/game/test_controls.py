"""Tests for src.game.controls - the humanized input layer.

controls.py does `from X import Y` for all its adb/image_processing
dependencies, so every mock target below patches the name as bound inside
`src.game.controls` (e.g. `controls.tap_screen`), not the original module.
"""
from unittest.mock import Mock

import pytest

import src.game.controls as controls
from src.core.config import CONFIG


# ---------------------------------------------------------------------------
# human_delay
# ---------------------------------------------------------------------------

class TestHumanDelay:
    def test_sleeps_for_delay_times_multiplier(self, monkeypatch):
        CONFIG._config["sleep_multiplier"] = 2.0
        fake_sleep = Mock()
        monkeypatch.setattr(controls.time, "sleep", fake_sleep)
        controls.human_delay(1.5)
        fake_sleep.assert_called_once_with(3.0)

    def test_defaults_multiplier_to_one_when_absent(self, monkeypatch):
        CONFIG._config.pop("sleep_multiplier", None)
        fake_sleep = Mock()
        monkeypatch.setattr(controls.time, "sleep", fake_sleep)
        controls.human_delay(2.0)
        fake_sleep.assert_called_once_with(2.0)


# ---------------------------------------------------------------------------
# humanized_tap
# ---------------------------------------------------------------------------

class TestHumanizedTap:
    def test_applies_normal_radius_jitter_and_taps(self, monkeypatch):
        CONFIG._config["randomization"] = {"critical_radius": 1, "normal_radius": 5}
        CONFIG._config["timings"] = {**CONFIG._config["timings"], "tap_delay": 0.3}

        # Fixed jitter: always return the lower bound passed to randint.
        monkeypatch.setattr(controls.random, "randint", lambda a, b: a)
        fake_tap = Mock()
        monkeypatch.setattr(controls, "tap_screen", fake_tap)
        fake_delay = Mock()
        monkeypatch.setattr(controls, "human_delay", fake_delay)

        controls.humanized_tap("dev1", 100, 200, critical=False)

        fake_tap.assert_called_once_with("dev1", 100 - 5, 200 - 5)
        fake_delay.assert_called_once_with(0.3)

    def test_applies_critical_radius_when_critical(self, monkeypatch):
        CONFIG._config["randomization"] = {"critical_radius": 1, "normal_radius": 5}
        CONFIG._config["timings"] = {**CONFIG._config["timings"], "tap_delay": 0.3}

        monkeypatch.setattr(controls.random, "randint", lambda a, b: a)
        fake_tap = Mock()
        monkeypatch.setattr(controls, "tap_screen", fake_tap)
        monkeypatch.setattr(controls, "human_delay", Mock())

        controls.humanized_tap("dev1", 100, 200, critical=True)

        fake_tap.assert_called_once_with("dev1", 100 - 1, 200 - 1)

    def test_custom_delay_overrides_config_tap_delay(self, monkeypatch):
        CONFIG._config["randomization"] = {"critical_radius": 1, "normal_radius": 5}
        CONFIG._config["timings"] = {**CONFIG._config["timings"], "tap_delay": 0.3}

        monkeypatch.setattr(controls.random, "randint", lambda a, b: 0)
        monkeypatch.setattr(controls, "tap_screen", Mock())
        fake_delay = Mock()
        monkeypatch.setattr(controls, "human_delay", fake_delay)

        controls.humanized_tap("dev1", 100, 200, delay=9.0)

        fake_delay.assert_called_once_with(9.0)


# ---------------------------------------------------------------------------
# humanized_long_press
# ---------------------------------------------------------------------------

class TestHumanizedLongPress:
    def test_success_applies_jitter_and_duration_and_returns_true(self, monkeypatch):
        CONFIG._config["randomization"] = {"critical_radius": 1, "normal_radius": 5}
        CONFIG._config["timings"] = {**CONFIG._config["timings"], "tap_delay": 0.2}

        monkeypatch.setattr(controls.random, "randint", lambda a, b: a)  # -radius
        monkeypatch.setattr(controls.random, "uniform", lambda a, b: 1.0)  # no jitter on duration
        fake_long_press = Mock(return_value=True)
        monkeypatch.setattr(controls, "long_press_screen", fake_long_press)
        fake_delay = Mock()
        monkeypatch.setattr(controls, "human_delay", fake_delay)

        result = controls.humanized_long_press("dev1", 100, 200, duration=2.0, critical=False)

        assert result is True
        fake_long_press.assert_called_once_with("dev1", 100 - 5, 200 - 5, 2000)
        fake_delay.assert_called_once_with(0.2)

    def test_underlying_failure_returns_false_without_delay(self, monkeypatch):
        CONFIG._config["randomization"] = {"critical_radius": 1, "normal_radius": 5}
        monkeypatch.setattr(controls.random, "randint", lambda a, b: 0)
        monkeypatch.setattr(controls.random, "uniform", lambda a, b: 1.0)
        monkeypatch.setattr(controls, "long_press_screen", Mock(return_value=False))
        fake_delay = Mock()
        monkeypatch.setattr(controls, "human_delay", fake_delay)

        result = controls.humanized_long_press("dev1", 100, 200)

        assert result is False
        fake_delay.assert_not_called()

    def test_exception_is_caught_and_returns_false(self, monkeypatch):
        CONFIG._config["randomization"] = {"critical_radius": 1, "normal_radius": 5}
        monkeypatch.setattr(controls.random, "randint", lambda a, b: 0)
        monkeypatch.setattr(controls.random, "uniform", Mock(side_effect=RuntimeError("boom")))

        result = controls.humanized_long_press("dev1", 100, 200)

        assert result is False


# ---------------------------------------------------------------------------
# handle_swipes
# ---------------------------------------------------------------------------

class TestHandleSwipes:
    def _set_common_config(self):
        CONFIG._config["ui_elements"] = {
            "swipe": {"start_x": "50%", "start_y": "30%", "end_x": "50%", "end_y": "80%"}
        }
        CONFIG._config["randomization"] = {
            "critical_radius": 1,
            "normal_radius": 5,
            "swipe_variance": {"position": "0%", "duration": 10},
        }
        CONFIG._config["timings"] = {
            **CONFIG._config["timings"],
            "swipe_duration": {"min": 100, "max": 100},
            "scroll_delay": 0,
        }

    def test_up_direction_maps_start_y_end_y_directly(self, monkeypatch):
        self._set_common_config()
        monkeypatch.setattr(controls, "get_screen_size", Mock(return_value=(1000, 2000)))
        fake_swipe = Mock()
        monkeypatch.setattr(controls, "swipe_screen", fake_swipe)
        monkeypatch.setattr(controls, "human_delay", Mock())

        controls.handle_swipes("dev1", direction="up", num_swipes=1)

        # up: start_y=30% of height, end_y=80% of height
        fake_swipe.assert_called_once_with("dev1", 500, 600, 500, 1600, 100)

    def test_down_direction_swaps_start_y_end_y_source_fields(self, monkeypatch):
        self._set_common_config()
        monkeypatch.setattr(controls, "get_screen_size", Mock(return_value=(1000, 2000)))
        fake_swipe = Mock()
        monkeypatch.setattr(controls, "swipe_screen", fake_swipe)
        monkeypatch.setattr(controls, "human_delay", Mock())

        controls.handle_swipes("dev1", direction="down", num_swipes=1)

        # down: start_y pulled from end_y%, end_y pulled from start_y%
        fake_swipe.assert_called_once_with("dev1", 500, 1600, 500, 600, 100)

    def test_num_swipes_controls_call_count(self, monkeypatch):
        self._set_common_config()
        monkeypatch.setattr(controls, "get_screen_size", Mock(return_value=(1000, 2000)))
        fake_swipe = Mock()
        monkeypatch.setattr(controls, "swipe_screen", fake_swipe)
        monkeypatch.setattr(controls, "human_delay", Mock())

        controls.handle_swipes("dev1", direction="up", num_swipes=4)

        assert fake_swipe.call_count == 4

    def test_variance_jitter_applied_within_configured_percent(self, monkeypatch):
        self._set_common_config()
        CONFIG._config["randomization"]["swipe_variance"]["position"] = "10%"
        monkeypatch.setattr(controls, "get_screen_size", Mock(return_value=(1000, 2000)))
        # Fixed jitter fraction instead of real randomness, so the offset is
        # exactly predictable: 10% variance * fixed 1.0 fraction * width/height.
        monkeypatch.setattr(controls.random, "uniform", lambda a, b: b)  # max jitter, e.g. +10%
        fake_swipe = Mock()
        monkeypatch.setattr(controls, "swipe_screen", fake_swipe)
        monkeypatch.setattr(controls, "human_delay", Mock())

        controls.handle_swipes("dev1", direction="up", num_swipes=1)

        args = fake_swipe.call_args[0]
        # start_x = 500 + 10% of 1000 = 600
        assert args[1] == 500 + 100
        # start_y = 600 + 10% of 2000 = 800
        assert args[2] == 600 + 200


# ---------------------------------------------------------------------------
# launch_game
# ---------------------------------------------------------------------------

class TestLaunchGame:
    def _set_common_config(self):
        CONFIG._config["package_name"] = "com.fun.lastwar.gp"
        CONFIG._config["timings"] = {
            **CONFIG._config["timings"],
            "app_close_wait": 0,
            "launch_max_wait": 30,
            "menu_animation": 0,
            "launch_wait": 0,
        }

    def _patch_common(self, monkeypatch):
        monkeypatch.setattr(controls, "force_stop_package", Mock())
        monkeypatch.setattr(controls, "launch_package", Mock())
        monkeypatch.setattr(controls, "human_delay", Mock())
        monkeypatch.setattr(controls.time, "sleep", Mock())
        monkeypatch.setattr(controls, "_take_and_load_screenshot", Mock(return_value="screenshot"))
        monkeypatch.setattr(controls, "humanized_tap", Mock())

    def _time_sequence(self, monkeypatch, values):
        it = iter(values)
        monkeypatch.setattr(controls.time, "time", lambda: next(it))

    def test_home_found_immediately_navigates_and_returns_true(self, monkeypatch):
        self._set_common_config()
        self._patch_common(monkeypatch)
        self._time_sequence(monkeypatch, [0, 1])  # start_time, one loop condition check

        def fake_find_template(device_id, template_name, existing_screenshot=None):
            if template_name == "home":
                return (10, 20)
            return None

        monkeypatch.setattr(controls, "find_template", Mock(side_effect=fake_find_template))
        fake_navigate = Mock(return_value=True)
        monkeypatch.setattr(controls, "navigate_home", fake_navigate)

        result = controls.launch_game("dev1")

        assert result is True
        fake_navigate.assert_called_once_with("dev1", True)

    def test_start_button_tapped_before_home_found(self, monkeypatch):
        self._set_common_config()
        self._patch_common(monkeypatch)
        # start_time, cond#1 (iteration 1), cond#2 (iteration 2)
        self._time_sequence(monkeypatch, [0, 1, 2])

        calls = {"n": 0}

        def fake_find_template(device_id, template_name, existing_screenshot=None):
            if template_name == "start":
                calls["n"] += 1
                return (5, 5) if calls["n"] == 1 else None
            if template_name == "home":
                return (10, 20) if calls["n"] >= 1 and existing_screenshot is None else None
            return None

        monkeypatch.setattr(controls, "find_template", Mock(side_effect=fake_find_template))
        fake_tap = Mock()
        monkeypatch.setattr(controls, "humanized_tap", fake_tap)
        fake_navigate = Mock(return_value=True)
        monkeypatch.setattr(controls, "navigate_home", fake_navigate)

        result = controls.launch_game("dev1")

        assert result is True
        fake_tap.assert_called_once_with("dev1", 5, 5)

    def test_timeout_without_finding_home_returns_false(self, monkeypatch):
        self._set_common_config()
        self._patch_common(monkeypatch)
        # start_time=0, then immediately exceed launch_max_wait so the loop
        # body never executes.
        self._time_sequence(monkeypatch, [0, 1000])

        monkeypatch.setattr(controls, "find_template", Mock(return_value=None))
        fake_navigate = Mock()
        monkeypatch.setattr(controls, "navigate_home", fake_navigate)

        result = controls.launch_game("dev1")

        assert result is False
        fake_navigate.assert_not_called()


# ---------------------------------------------------------------------------
# navigate_home
# ---------------------------------------------------------------------------

class TestNavigateHome:
    def _set_common_config(self):
        CONFIG._config["timings"] = {**CONFIG._config["timings"], "menu_animation": 0}
        CONFIG._config["max_home_attempts"] = 5

    def test_already_home_short_circuits_without_pressing_back(self, monkeypatch):
        self._set_common_config()
        monkeypatch.setattr(controls, "find_template", Mock(return_value=(1, 1)))
        fake_back = Mock()
        monkeypatch.setattr(controls, "press_back", fake_back)
        monkeypatch.setattr(controls, "human_delay", Mock())

        result = controls.navigate_home("dev1", force=False)

        assert result is True
        fake_back.assert_not_called()

    def test_quit_dialog_is_drained_then_returns_true(self, monkeypatch):
        self._set_common_config()
        monkeypatch.setattr(controls, "press_back", Mock())
        monkeypatch.setattr(controls, "human_delay", Mock())

        # find_template("quit") is called repeatedly: appears twice, then
        # gone - the nested `while quit_loc:` loop must terminate on the
        # third call or this test would hang.
        quit_responses = iter([(1, 1), (1, 1), None])

        def fake_find_template(device_id, template_name, existing_screenshot=None):
            assert template_name == "quit"
            return next(quit_responses)

        monkeypatch.setattr(controls, "find_template", Mock(side_effect=fake_find_template))

        result = controls.navigate_home("dev1", force=True)

        assert result is True

    def test_max_attempts_exhausted_returns_false(self, monkeypatch):
        self._set_common_config()
        CONFIG._config["max_home_attempts"] = 3
        monkeypatch.setattr(controls, "press_back", Mock())
        monkeypatch.setattr(controls, "human_delay", Mock())
        monkeypatch.setattr(controls, "find_template", Mock(return_value=None))

        result = controls.navigate_home("dev1", force=True)

        assert result is False

    def test_exception_is_caught_and_returns_false(self, monkeypatch):
        self._set_common_config()
        monkeypatch.setattr(controls, "press_back", Mock(side_effect=RuntimeError("boom")))

        result = controls.navigate_home("dev1", force=True)

        assert result is False
