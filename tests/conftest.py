"""Shared pytest fixtures.

A few modules under `src/` perform real filesystem/config I/O at *import*
time (before any test-level monkeypatch can run):

- `src.core.logging` creates `logs/` and opens `logging.FileHandler(
  'logs/app.log')`, attaching handlers to the process-wide `app_logger`
  singleton once.
- `src.core.device` runs `ensure_dir("tmp")` at module scope.
- `src.core.config` builds the `CONFIG` singleton by reading the real,
  tracked `config/config.json` / `config/automation.json` off disk.

These are accepted as harmless, pre-existing, gitignored side effects
(identical to what running `cli.py` itself does) rather than fought with a
session-wide `chdir` before first import - doing so would fight pytest's own
collection and every test's use of the real, tracked template PNGs under
`config/templates/`. What *is* enforced below is that no test may leave a
lasting mark on tracked files: `CONFIG`'s mutable dict attributes are
snapshotted/restored around every test, and anything that needs `state/` or
a fake `config/` tree uses `tmp_path` explicitly.
"""
import numpy as np
import pytest

from src.core import image_processing
from src.core.config import CONFIG


@pytest.fixture(autouse=True)
def reset_config():
    """Snapshot/restore CONFIG's mutable state around every test.

    CONFIG is imported by reference everywhere (`from .config import
    CONFIG`), so mutating attributes on this one shared object is visible to
    every consumer module without needing to patch each import site
    individually - and restoring it here means a test that does
    `CONFIG._adb["type"] = "tcp"` (or relies on `get_device_list`'s
    real-SDK-path fallback mutating `CONFIG.adb["binary_path"]` in place)
    can never leak into another test.
    """
    snapshot = {
        "_config": dict(CONFIG._config),
        "_automation_config": dict(CONFIG._automation_config),
        "_control_list": dict(CONFIG._control_list),
        "_adb": dict(CONFIG._adb),
    }
    yield CONFIG
    CONFIG._config = snapshot["_config"]
    CONFIG._automation_config = snapshot["_automation_config"]
    CONFIG._control_list = snapshot["_control_list"]
    CONFIG._adb = snapshot["_adb"]


@pytest.fixture(autouse=True)
def clear_template_cache():
    """image_processing._template_cache is a module-level dict with no
    reset API. Clear it before and after every test so a template loaded
    (or a synthetic np.ndarray injected via monkeypatched _load_template)
    in one test never leaks into another via the (device, template_name)
    cache key."""
    image_processing._template_cache.clear()
    yield
    image_processing._template_cache.clear()


@pytest.fixture
def isolated_repo_cwd(tmp_path, monkeypatch):
    """Opt-in (NOT autouse) fixture for the handful of tests that construct
    objects with hardcoded-relative-path defaults (e.g. `AutomationState()`
    defaulting to `state/automation_state.json`, `cli.py`'s module-level
    `config/automation.json` read, `MainAutomation.load_automation_config`)
    and need those reads/writes to land in a scratch directory instead of
    the real repo. Builds a minimal `config/automation.json` there so those
    reads succeed."""
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "automation.json").write_text(
        '{"time_checks": {}, "scheduled_events": {}}'
    )
    return tmp_path


class _FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def mock_subprocess_run(monkeypatch):
    """Patch `<module>.subprocess.run` and return a controller object with:

    - `.set_result(module, stdout="", stderr="", returncode=0)`: patches
      `subprocess.run` on the given module object to always return a
      canned result.
    - `.calls`: list of (args, kwargs) tuples recording every call made
      across every patched module, in call order.

    Usage:
        def test_x(mock_subprocess_run):
            import src.core.adb as adb
            mock_subprocess_run.set_result(adb, stdout="List of devices...\\n")
            ...
            assert mock_subprocess_run.calls[0][0][0] == [...]
    """

    class Controller:
        def __init__(self):
            self.calls = []

        def set_result(self, module, stdout="", stderr="", returncode=0):
            def fake_run(*args, **kwargs):
                self.calls.append((args, kwargs))
                return _FakeCompletedProcess(stdout=stdout, stderr=stderr, returncode=returncode)

            monkeypatch.setattr(module.subprocess, "run", fake_run)
            return fake_run

        def set_side_effect(self, module, side_effect):
            def fake_run(*args, **kwargs):
                self.calls.append((args, kwargs))
                if callable(side_effect):
                    return side_effect(*args, **kwargs)
                raise side_effect

            monkeypatch.setattr(module.subprocess, "run", fake_run)
            return fake_run

    return Controller()


@pytest.fixture
def synthetic_screenshot():
    """Build a small synthetic BGR screenshot (np.ndarray) with one or more
    stamped rectangular sub-regions, so template-matching functions can be
    driven end-to-end via `existing_screenshot` without any ADB/cv2.imread/
    disk dependency.

    Each region is filled with a distinct, seeded PSEUDO-RANDOM noise
    pattern rather than a flat color: cv2.matchTemplate's TM_CCOEFF_NORMED
    is a normalized cross-correlation, which is degenerate over flat/
    zero-variance patches (a solid-color region can spuriously "match" a
    same-solid-color template at score ~1.0 almost anywhere, including
    against a background of a *different* flat color, once both are
    variance-normalized) - noise gives each region a genuine, position-
    specific signature so match/no-match assertions are meaningful.

    Returns a builder function `build(width, height, regions)` where
    `regions` is a list of (x, y, w, h) tuples, or (x, y, w, h, seed) to
    control/differentiate the noise pattern explicitly (defaults to a
    distinct seed per region index). Returns (screenshot, [(x,y,w,h), ...]).
    """

    def build(width=200, height=150, regions=None):
        background_rng = np.random.default_rng(0)
        img = background_rng.integers(0, 60, size=(height, width, 3), dtype=np.uint8)
        if regions is None:
            regions = [(60, 40, 30, 20)]
        boxes = []
        for i, region in enumerate(regions):
            x, y, w, h = region[:4]
            seed = region[4] if len(region) > 4 else 1000 + i
            rng = np.random.default_rng(seed)
            patch = rng.integers(120, 256, size=(h, w, 3), dtype=np.uint8)
            img[y:y + h, x:x + w] = patch
            boxes.append((x, y, w, h))
        return img, boxes

    return build


@pytest.fixture
def synthetic_template(synthetic_screenshot):
    """Crop a synthetic_screenshot's stamped sub-region into its own small
    np.ndarray, to use as the "loaded template" when monkeypatching
    image_processing._load_template."""

    def build(screenshot, box):
        x, y, w, h = box
        return screenshot[y:y + h, x:x + w].copy()

    return build
