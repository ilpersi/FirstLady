"""Tests for src.core.image_processing.

Template-matching logic is driven end-to-end via the `existing_screenshot`
parameter with synthetic numpy arrays - the one genuine DI seam in this
module - so most tests need no ADB/cv2.imread/disk mocking at all.
"""
import numpy as np
import pytest

from src.core import image_processing
from src.core.config import CONFIG


def _pattern_screenshot(width=200, height=150, boxes=None, seed=0):
    """Build a screenshot with a random-noise background and one or more
    byte-identical random-noise patches stamped in at the given (x, y, w, h)
    boxes (all boxes must share one size). Unlike flat/uniform-color
    regions (whose zero variance makes cv2's TM_CCOEFF_NORMED degenerate -
    it can score a "match" of 1.0 almost anywhere against a flat
    background), noise patches give matchTemplate an unambiguous peak.

    Returns (screenshot, boxes, template) where `template` is the exact
    pixel content stamped at every box.
    """
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 60, size=(height, width, 3), dtype=np.uint8)
    if boxes is None:
        boxes = [(60, 40, 30, 20)]
    w0, h0 = boxes[0][2], boxes[0][3]
    template = np.random.default_rng(seed + 1000).integers(
        180, 255, size=(h0, w0, 3), dtype=np.uint8
    )
    for (x, y, w, h) in boxes:
        assert (w, h) == (w0, h0), "all boxes must share the first box's size"
        img[y:y + h, x:x + w] = template
    return img, boxes, template


def _unrelated_template(w=30, h=20, seed=9999):
    return np.random.default_rng(seed).integers(180, 255, size=(h, w, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# _load_template
# ---------------------------------------------------------------------------

class TestLoadTemplate:
    def test_missing_template_name_in_config_returns_none(self):
        CONFIG._config["templates"] = {"device": "default"}
        result, config = image_processing._load_template("nonexistent")
        assert result is None
        assert config is None

    def test_cache_hit_avoids_reloading(self, monkeypatch, tmp_path):
        CONFIG._config["templates"] = {
            "device": "default",
            "foo": {"path": "foo.png", "threshold": 0.8},
        }
        calls = {"count": 0}

        def fake_imread(path):
            calls["count"] += 1
            return np.zeros((5, 5, 3), dtype=np.uint8)

        monkeypatch.setattr(image_processing.cv2, "imread", fake_imread)
        monkeypatch.setattr(image_processing.Path, "exists", lambda self: True)

        first = image_processing._load_template("foo")
        second = image_processing._load_template("foo")

        assert calls["count"] == 1
        # The cache returns the exact same tuple object on a hit; the first
        # call constructs a fresh (template, config) tuple from the same
        # underlying array/dict it just cached, so compare the elements'
        # identity rather than the outer tuples'.
        assert first[0] is second[0]
        assert first[1] is second[1]

    def test_cache_miss_loads_and_caches(self, monkeypatch):
        CONFIG._config["templates"] = {
            "device": "default",
            "foo": {"path": "foo.png", "threshold": 0.8},
        }
        template_array = np.ones((4, 4, 3), dtype=np.uint8)
        monkeypatch.setattr(image_processing.cv2, "imread", lambda path: template_array)
        monkeypatch.setattr(image_processing.Path, "exists", lambda self: True)

        result, config = image_processing._load_template("foo")

        assert result is template_array
        assert config == {"path": "foo.png", "threshold": 0.8}
        assert ("default", "foo") in image_processing._template_cache

    def test_default_device_missing_file_returns_none(self, monkeypatch):
        CONFIG._config["templates"] = {
            "device": "default",
            "foo": {"path": "foo.png", "threshold": 0.8},
        }
        monkeypatch.setattr(image_processing.Path, "exists", lambda self: False)

        result, config = image_processing._load_template("foo")

        assert result is None
        assert config is None

    def test_device_specific_falls_back_to_default_when_missing(self, monkeypatch):
        CONFIG._config["templates"] = {
            "device": "custom_device",
            "foo": {"path": "foo.png", "threshold": 0.8},
        }

        def fake_exists(self):
            # The custom_device path doesn't exist, but the default one does.
            return "default" in str(self)

        template_array = np.full((3, 3, 3), 7, dtype=np.uint8)
        monkeypatch.setattr(image_processing.Path, "exists", fake_exists)
        monkeypatch.setattr(image_processing.cv2, "imread", lambda path: template_array)

        result, config = image_processing._load_template("foo")

        assert result is template_array
        assert ("custom_device", "foo") in image_processing._template_cache

    def test_device_specific_and_default_both_missing_returns_none(self, monkeypatch):
        CONFIG._config["templates"] = {
            "device": "custom_device",
            "foo": {"path": "foo.png", "threshold": 0.8},
        }
        monkeypatch.setattr(image_processing.Path, "exists", lambda self: False)

        result, config = image_processing._load_template("foo")

        assert result is None
        assert config is None

    def test_imread_failure_returns_none(self, monkeypatch):
        CONFIG._config["templates"] = {
            "device": "default",
            "foo": {"path": "foo.png", "threshold": 0.8},
        }
        monkeypatch.setattr(image_processing.Path, "exists", lambda self: True)
        monkeypatch.setattr(image_processing.cv2, "imread", lambda path: None)

        result, config = image_processing._load_template("foo")

        assert result is None
        assert config is None


# ---------------------------------------------------------------------------
# find_template / find_template_debug
# ---------------------------------------------------------------------------

def _patch_load_template(monkeypatch, template, threshold=0.8, path="foo.png"):
    monkeypatch.setattr(
        image_processing,
        "_load_template",
        lambda name: (template, {"threshold": threshold, "path": path}),
    )


class TestFindTemplate:
    def test_match_above_threshold_returns_center(self, monkeypatch):
        screenshot, boxes, template = _pattern_screenshot()
        _patch_load_template(monkeypatch, template, threshold=0.8)

        result = image_processing.find_template("device1", "foo", existing_screenshot=screenshot)

        x, y, w, h = boxes[0]
        assert result == (x + w // 2, y + h // 2)

    def test_match_below_threshold_returns_none(self, monkeypatch):
        screenshot, boxes, _ = _pattern_screenshot()
        # A template that doesn't resemble anything in the screenshot.
        w, h = boxes[0][2], boxes[0][3]
        unrelated_template = _unrelated_template(w, h)
        _patch_load_template(monkeypatch, unrelated_template, threshold=0.9)

        result = image_processing.find_template("device1", "foo", existing_screenshot=screenshot)

        assert result is None

    def test_load_template_failure_short_circuits(self, monkeypatch):
        monkeypatch.setattr(image_processing, "_load_template", lambda name: (None, None))

        result = image_processing.find_template("device1", "foo")

        assert result is None

    def test_existing_screenshot_bypasses_capture(self, monkeypatch):
        screenshot, boxes, template = _pattern_screenshot()
        _patch_load_template(monkeypatch, template, threshold=0.8)

        def boom(device_id):
            raise AssertionError("_take_and_load_screenshot should not be called")

        monkeypatch.setattr(image_processing, "_take_and_load_screenshot", boom)

        result = image_processing.find_template("device1", "foo", existing_screenshot=screenshot)

        assert result is not None

    def test_debug_mode_writes_overlay_file(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tmp").mkdir()
        screenshot, boxes, template = _pattern_screenshot()
        _patch_load_template(monkeypatch, template, threshold=0.8)
        CONFIG._config["debug_mode"] = True

        image_processing.find_template("device1", "foo", existing_screenshot=screenshot)

        assert (tmp_path / "tmp" / "debug_find_foo.png").exists()


class TestFindTemplateDebug:
    def test_found_true_above_threshold(self, monkeypatch):
        screenshot, boxes, template = _pattern_screenshot()
        _patch_load_template(monkeypatch, template, threshold=0.8)

        result = image_processing.find_template_debug("device1", "foo", existing_screenshot=screenshot)

        assert result["found"] is True
        assert result["confidence"] >= 0.8

    def test_found_false_below_threshold(self, monkeypatch):
        screenshot, boxes, _ = _pattern_screenshot()
        w, h = boxes[0][2], boxes[0][3]
        unrelated_template = _unrelated_template(w, h)
        _patch_load_template(monkeypatch, unrelated_template, threshold=0.9)

        result = image_processing.find_template_debug("device1", "foo", existing_screenshot=screenshot)

        assert result["found"] is False

    def test_load_template_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(image_processing, "_load_template", lambda name: (None, None))

        result = image_processing.find_template_debug("device1", "foo")

        assert result is None


# ---------------------------------------------------------------------------
# find_all_templates
# ---------------------------------------------------------------------------

class TestFindAllTemplates:
    def test_finds_multiple_identical_regions(self, monkeypatch):
        boxes_in = [(10, 10, 20, 15), (100, 90, 20, 15)]
        screenshot, boxes, template = _pattern_screenshot(boxes=boxes_in)
        _patch_load_template(monkeypatch, template, threshold=0.8)

        results = image_processing.find_all_templates("device1", "foo", existing_screenshot=screenshot)

        assert len(results) == 2
        expected_centers = {
            (x + w // 2, y + h // 2) for (x, y, w, h) in boxes
        }
        assert set(results) == expected_centers

    def test_search_region_crops_and_offsets_coordinates(self, monkeypatch):
        boxes_in = [(10, 10, 20, 15), (100, 90, 20, 15)]
        screenshot, boxes, template = _pattern_screenshot(boxes=boxes_in)
        _patch_load_template(monkeypatch, template, threshold=0.8)

        # Search region only covers the second stamped box.
        search_region = (80, 70, 200, 150)
        results = image_processing.find_all_templates(
            "device1", "foo", search_region=search_region, existing_screenshot=screenshot
        )

        x, y, w, h = boxes[1]
        assert results == [(x + w // 2, y + h // 2)]

    def test_max_matches_caps_results(self, monkeypatch):
        boxes_in = [(10, 10, 20, 15), (100, 90, 20, 15)]
        screenshot, boxes, template = _pattern_screenshot(boxes=boxes_in)
        _patch_load_template(monkeypatch, template, threshold=0.8)

        results = image_processing.find_all_templates(
            "device1", "foo", existing_screenshot=screenshot, max_matches=1
        )

        assert len(results) <= 1

    def test_load_template_failure_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(image_processing, "_load_template", lambda name: (None, None))

        results = image_processing.find_all_templates("device1", "foo")

        assert results == []

    def test_debug_mode_writes_file(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tmp").mkdir()
        screenshot, boxes, template = _pattern_screenshot()
        _patch_load_template(monkeypatch, template, threshold=0.8)
        CONFIG._config["debug_mode"] = True

        image_processing.find_all_templates("device1", "foo", existing_screenshot=screenshot)

        matches = list((tmp_path / "tmp").glob("debug_template_*"))
        assert len(matches) == 1


# ---------------------------------------------------------------------------
# wait_for_image
# ---------------------------------------------------------------------------

class TestWaitForImage:
    def test_returns_coords_once_found(self, monkeypatch):
        times = iter([0.0, 0.5, 1.0, 1.5, 2.0, 100.0])
        monkeypatch.setattr(image_processing.time, "time", lambda: next(times))
        sleep_calls = []
        monkeypatch.setattr(image_processing.time, "sleep", lambda s: sleep_calls.append(s))

        find_calls = {"count": 0}

        def fake_find_template(device_id, template_name, existing_screenshot=None):
            find_calls["count"] += 1
            if find_calls["count"] < 3:
                return None
            return (5, 5)

        monkeypatch.setattr(image_processing, "find_template", fake_find_template)

        result = image_processing.wait_for_image("device1", "foo", timeout=10.0, interval=0.5)

        assert result == (5, 5)
        assert len(sleep_calls) == 2

    def test_timeout_returns_none(self, monkeypatch):
        times = iter([0.0, 1.0, 2.0, 11.0])
        monkeypatch.setattr(image_processing.time, "time", lambda: next(times))
        monkeypatch.setattr(image_processing.time, "sleep", lambda s: None)
        monkeypatch.setattr(image_processing, "find_template", lambda *a, **kw: None)

        result = image_processing.wait_for_image("device1", "foo", timeout=10.0, interval=1.0)

        assert result is None


# ---------------------------------------------------------------------------
# compare_screenshots
# ---------------------------------------------------------------------------

class TestCompareScreenshots:
    def test_none_args_return_false(self):
        img = np.zeros((5, 5, 3), dtype=np.uint8)
        assert not image_processing.compare_screenshots(None, img)
        assert not image_processing.compare_screenshots(img, None)
        assert not image_processing.compare_screenshots(None, None)

    def test_shape_mismatch_returns_false(self):
        img1 = np.zeros((5, 5, 3), dtype=np.uint8)
        img2 = np.zeros((6, 6, 3), dtype=np.uint8)
        assert not image_processing.compare_screenshots(img1, img2)

    def test_identical_images_return_true(self):
        CONFIG._config["match_threshold"] = 0.8
        img = np.random.randint(0, 255, (20, 20, 3), dtype=np.uint8)
        assert image_processing.compare_screenshots(img, img.copy())

    def test_different_images_return_false(self):
        CONFIG._config["match_threshold"] = 0.8
        img1 = np.zeros((20, 20, 3), dtype=np.uint8)
        img2 = np.full((20, 20, 3), 255, dtype=np.uint8)
        assert not image_processing.compare_screenshots(img1, img2)


# ---------------------------------------------------------------------------
# find_and_tap_template
# ---------------------------------------------------------------------------

class TestFindAndTapTemplate:
    def test_no_timeout_uses_find_template_with_existing_screenshot(self, monkeypatch):
        captured = {}

        def fake_find_template(device_id, template_name, existing_screenshot=None):
            captured["existing_screenshot"] = existing_screenshot
            return (5, 6)

        monkeypatch.setattr(image_processing, "find_template", fake_find_template)
        monkeypatch.setattr(
            image_processing, "wait_for_image", lambda *a, **kw: (999, 999)
        )

        tap_calls = []
        monkeypatch.setattr(
            "src.game.controls.humanized_tap",
            lambda device_id, x, y: tap_calls.append((x, y)),
        )

        screenshot = object()
        result = image_processing.find_and_tap_template(
            "device1", "foo", existing_screenshot=screenshot
        )

        assert result is True
        assert captured["existing_screenshot"] is screenshot
        assert tap_calls == [(5, 6)]

    def test_timeout_uses_wait_for_image_not_find_template(self, monkeypatch):
        monkeypatch.setattr(
            image_processing,
            "find_template",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("find_template should not be called")),
        )
        monkeypatch.setattr(image_processing, "wait_for_image", lambda *a, **kw: (7, 8))

        tap_calls = []
        monkeypatch.setattr(
            "src.game.controls.humanized_tap",
            lambda device_id, x, y: tap_calls.append((x, y)),
        )

        result = image_processing.find_and_tap_template("device1", "foo", timeout=5.0)

        assert result is True
        assert tap_calls == [(7, 8)]

    def test_location_none_returns_false_without_tapping(self, monkeypatch):
        monkeypatch.setattr(image_processing, "find_template", lambda *a, **kw: None)
        tap_calls = []
        monkeypatch.setattr(
            "src.game.controls.humanized_tap",
            lambda device_id, x, y: tap_calls.append((x, y)),
        )

        result = image_processing.find_and_tap_template("device1", "foo")

        assert result is False
        assert tap_calls == []

    def test_long_press_calls_humanized_long_press_with_duration(self, monkeypatch):
        monkeypatch.setattr(image_processing, "find_template", lambda *a, **kw: (1, 2))
        long_press_calls = []
        monkeypatch.setattr(
            "src.game.controls.humanized_long_press",
            lambda device_id, x, y, duration=1.0: long_press_calls.append((x, y, duration)),
        )

        result = image_processing.find_and_tap_template(
            "device1", "foo", long_press=True, press_duration=2.5
        )

        assert result is True
        assert long_press_calls == [(1, 2, 2.5)]
