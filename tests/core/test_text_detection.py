"""Tests for src.core.text_detection."""
import typing

import numpy as np
import pytest

from src.core import text_detection
from src.core.config import CONFIG


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------

class TestCleanText:
    def test_strips_non_alnum(self):
        assert text_detection.clean_text("[ABC]-123!") == "ABC123"

    def test_preserves_alnum(self):
        assert text_detection.clean_text("abc123XYZ") == "abc123XYZ"

    def test_empty_string(self):
        assert text_detection.clean_text("") == ""


# ---------------------------------------------------------------------------
# build_alliance_whitelist
# ---------------------------------------------------------------------------

class TestBuildAllianceWhitelist:
    def test_deduplicated_sorted_chars_across_tags(self):
        # build_alliance_whitelist reads via CONFIG.get('control_list', ...),
        # the dict-style getter backed by CONFIG._config - not the
        # .control_list property (which is resolved once at load time into
        # a separate _control_list attribute).
        CONFIG._config["control_list"] = {"whitelist": {"alliance": ["ABC", "BCD"]}}
        result = text_detection.build_alliance_whitelist()
        assert result == "".join(sorted(set("ABC") | set("BCD")))

    def test_empty_whitelist_returns_empty_string(self):
        CONFIG._config["control_list"] = {"whitelist": {"alliance": []}}
        assert text_detection.build_alliance_whitelist() == ""

    def test_missing_control_list_key_returns_empty_string(self):
        CONFIG._config.pop("control_list", None)
        assert text_detection.build_alliance_whitelist() == ""


# ---------------------------------------------------------------------------
# extract_text_from_region
# ---------------------------------------------------------------------------

class TestExtractTextFromRegion:
    def test_img_none_and_capture_fails_returns_empty_tuple(self, monkeypatch):
        monkeypatch.setattr(text_detection, "_take_and_load_screenshot", lambda device_id: None)

        result = text_detection.extract_text_from_region("device1", (0, 0, 10, 10), img=None)

        assert result == ("", "")

    def test_bracket_text_extracted(self, monkeypatch, synthetic_screenshot):
        screenshot, _ = synthetic_screenshot(width=200, height=150)
        monkeypatch.setattr(
            text_detection.pytesseract, "image_to_string", lambda img, lang, config: "[ABC] SomeName"
        )

        text, original = text_detection.extract_text_from_region(
            "device1", (0, 0, 50, 20), img=screenshot
        )

        assert text == "ABC"
        assert original == "[ABC] SomeName"

    def test_empty_ocr_result_returns_empty_text(self, monkeypatch, synthetic_screenshot):
        screenshot, _ = synthetic_screenshot(width=200, height=150)
        monkeypatch.setattr(text_detection.pytesseract, "image_to_string", lambda img, lang, config: "")

        text, original = text_detection.extract_text_from_region(
            "device1", (0, 0, 50, 20), img=screenshot
        )

        assert text == ""
        assert original == ""

    def test_non_eng_language_does_not_raise_and_returns_empty(self, monkeypatch, synthetic_screenshot):
        """Regression test for bug #6: languages != 'eng' used to reference
        `original_text` before it was ever assigned, raising
        UnboundLocalError."""
        screenshot, _ = synthetic_screenshot(width=200, height=150)

        text, original = text_detection.extract_text_from_region(
            "device1", (0, 0, 50, 20), languages="chi_sim", img=screenshot
        )

        assert (text, original) == ("", "")

    def test_non_eng_language_as_list_does_not_raise(self, synthetic_screenshot):
        screenshot, _ = synthetic_screenshot(width=200, height=150)

        text, original = text_detection.extract_text_from_region(
            "device1", (0, 0, 50, 20), languages=["chi_sim", "eng"], img=screenshot
        )

        assert (text, original) == ("", "")

    def test_whitelist_passed_to_tesseract_config(self, monkeypatch, synthetic_screenshot):
        """Regression test for bug #5: the tessedit_char_whitelist config
        fragment was commented out, so ALLIANCE_CHARS was computed but never
        actually applied to the OCR call."""
        monkeypatch.setattr(text_detection, "ALLIANCE_CHARS", "ABC123")
        screenshot, _ = synthetic_screenshot(width=200, height=150)

        captured = {}

        def fake_image_to_string(img, lang, config):
            captured["config"] = config
            return "ABC"

        monkeypatch.setattr(text_detection.pytesseract, "image_to_string", fake_image_to_string)

        text_detection.extract_text_from_region("device1", (0, 0, 50, 20), img=screenshot)

        assert "tessedit_char_whitelist=ABC123" in captured["config"]

    def test_return_annotation_is_tuple_of_str(self):
        """Regression test for bug #7: the declared return annotation was
        `-> str` despite every branch returning a 2-tuple."""
        hints = typing.get_type_hints(text_detection.extract_text_from_region)
        assert hints["return"] == typing.Tuple[str, str]


# ---------------------------------------------------------------------------
# get_text_regions
# ---------------------------------------------------------------------------

class TestGetTextRegions:
    def _bracket_template(self):
        # shape[0] = height = 20, shape[1] = width = 10
        return np.zeros((20, 10, 3), dtype=np.uint8)

    def test_valid_bracket_pair_found(self, monkeypatch, synthetic_screenshot):
        screenshot, _ = synthetic_screenshot(width=1000, height=600)
        monkeypatch.setattr(text_detection, "get_screen_size", lambda device_id: (1000, 600))
        monkeypatch.setattr(
            text_detection, "_load_template", lambda name: (self._bracket_template(), {"threshold": 0.8})
        )

        def fake_find_all_templates(device_id, template_name, search_region=None, existing_screenshot=None):
            if template_name == "left_bracket":
                return [(100, 295)]
            if template_name == "right_bracket":
                return [(150, 298)]
            return []

        monkeypatch.setattr(text_detection, "find_all_templates", fake_find_all_templates)

        alliance_region, name_region, img = text_detection.get_text_regions(
            (500, 300), "device1", existing_screenshot=screenshot
        )

        assert alliance_region == (95, 283, 165, 307)
        assert name_region == (160, 283, 480, 307)
        assert img is screenshot

    def test_no_valid_pair_uses_fallback_split(self, monkeypatch, synthetic_screenshot):
        screenshot, _ = synthetic_screenshot(width=1000, height=600)
        monkeypatch.setattr(text_detection, "get_screen_size", lambda device_id: (1000, 600))
        monkeypatch.setattr(
            text_detection, "_load_template", lambda name: (self._bracket_template(), {"threshold": 0.8})
        )
        monkeypatch.setattr(text_detection, "find_all_templates", lambda *a, **kw: [])

        alliance_region, name_region, img = text_detection.get_text_regions(
            (500, 300), "device1", existing_screenshot=screenshot
        )

        assert alliance_region == (40, 282, 260, 300)
        assert name_region == (260, 273, 480, 333)

    def test_debug_mode_saves_debug_region(self, monkeypatch, synthetic_screenshot):
        screenshot, _ = synthetic_screenshot(width=1000, height=600)
        monkeypatch.setattr(text_detection, "get_screen_size", lambda device_id: (1000, 600))
        monkeypatch.setattr(
            text_detection, "_load_template", lambda name: (self._bracket_template(), {"threshold": 0.8})
        )

        def fake_find_all_templates(device_id, template_name, search_region=None, existing_screenshot=None):
            if template_name == "left_bracket":
                return [(100, 295)]
            if template_name == "right_bracket":
                return [(150, 298)]
            return []

        monkeypatch.setattr(text_detection, "find_all_templates", fake_find_all_templates)
        CONFIG._config["debug_mode"] = True

        calls = []
        monkeypatch.setattr(
            text_detection, "save_debug_region", lambda device_id, region, prefix: calls.append((device_id, region, prefix))
        )

        alliance_region, _, _ = text_detection.get_text_regions(
            (500, 300), "device1", existing_screenshot=screenshot
        )

        assert calls == [("device1", alliance_region, "alliance")]

    def test_img_none_and_capture_fails_returns_zero_regions(self, monkeypatch):
        monkeypatch.setattr(text_detection, "get_screen_size", lambda device_id: (1000, 600))
        monkeypatch.setattr(text_detection, "_take_and_load_screenshot", lambda device_id: None)

        alliance_region, name_region, img = text_detection.get_text_regions((500, 300), "device1")

        assert alliance_region == (0, 0, 0, 0)
        assert name_region == (0, 0, 0, 0)
        assert img is None


# ---------------------------------------------------------------------------
# log_rejected_alliance
# ---------------------------------------------------------------------------

class TestLogRejectedAlliance:
    def test_logs_line_without_debug_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "logs").mkdir()

        text_detection.log_rejected_alliance("XYZ", "original xyz text")

        log_contents = (tmp_path / "logs" / "rejected_alliances.log").read_text()
        assert "Final: XYZ" in log_contents
        assert "original xyz text" in log_contents

    def test_copies_existing_debug_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "logs").mkdir()
        (tmp_path / "tmp").mkdir()
        (tmp_path / "tmp" / "debug_alliance_processed.png").write_bytes(b"fake-png-data")

        text_detection.log_rejected_alliance("XYZ", "original xyz text")

        reject_dirs = list((tmp_path / "tmp" / "rejects").iterdir())
        assert len(reject_dirs) == 1
        assert (reject_dirs[0] / "processed.png").read_bytes() == b"fake-png-data"
        # Files that don't exist are silently skipped, not an error.
        assert not (reject_dirs[0] / "original.png").exists()

    def test_does_not_raise_when_logs_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # No logs/ or tmp/ directories created - function must swallow the
        # resulting exception rather than propagate it.
        text_detection.log_rejected_alliance("XYZ")
