"""Tests for src.core.device - mocks subprocess.run at src.core.device.subprocess.run."""
import subprocess as real_subprocess

import src.core.device as device
from src.core.config import CONFIG


# ---------------------------------------------------------------------------
# capture_screenshot_bytes
# ---------------------------------------------------------------------------

class TestCaptureScreenshotBytes:
    def test_success_returns_bytes(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        payload = b"\x89PNGfakebytes"
        monkeypatch.setattr(
            device.subprocess, "run",
            lambda *a, **k: type("R", (), {"stdout": payload, "stderr": b"", "returncode": 0})(),
        )
        assert device.capture_screenshot_bytes("dev1") == payload

    def test_nonzero_returncode_returns_none(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        monkeypatch.setattr(
            device.subprocess, "run",
            lambda *a, **k: type("R", (), {"stdout": b"", "stderr": b"error", "returncode": 1})(),
        )
        assert device.capture_screenshot_bytes("dev1") is None

    def test_exception_returns_none(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        monkeypatch.setattr(device.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert device.capture_screenshot_bytes("dev1") is None


# ---------------------------------------------------------------------------
# pull_screenshot_to
# ---------------------------------------------------------------------------

class TestPullScreenshotTo:
    def test_success_writes_file_and_creates_parent_dirs(self, tmp_path, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        output_path = tmp_path / "nested" / "dir" / "screen.png"

        def fake_run(cmd, stdout=None, **kwargs):
            stdout.write(b"png-bytes")
            return type("R", (), {"returncode": 0, "stderr": b""})()

        monkeypatch.setattr(device.subprocess, "run", fake_run)
        assert device.pull_screenshot_to("dev1", str(output_path)) is True
        assert output_path.exists()
        assert output_path.read_bytes() == b"png-bytes"

    def test_nonzero_returncode_returns_false(self, tmp_path, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        output_path = tmp_path / "screen.png"

        def fake_run(cmd, stdout=None, **kwargs):
            return type("R", (), {"returncode": 1, "stderr": b"boom"})()

        monkeypatch.setattr(device.subprocess, "run", fake_run)
        assert device.pull_screenshot_to("dev1", str(output_path)) is False

    def test_exception_returns_false(self, tmp_path, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        output_path = tmp_path / "screen.png"
        monkeypatch.setattr(device.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert device.pull_screenshot_to("dev1", str(output_path)) is False


# ---------------------------------------------------------------------------
# take_screenshot
# ---------------------------------------------------------------------------

class TestTakeScreenshot:
    def test_delegates_to_pull_screenshot_to_with_fixed_path(self, monkeypatch):
        calls = []
        monkeypatch.setattr(device, "pull_screenshot_to", lambda device_id, path: calls.append((device_id, path)) or True)
        assert device.take_screenshot("dev1") is True
        assert calls == [("dev1", "tmp/screen.png")]


# ---------------------------------------------------------------------------
# cleanup_device_screenshots (bug #2 regression)
# ---------------------------------------------------------------------------

class TestCleanupDeviceScreenshots:
    def test_calls_subprocess_with_shell_true(self, monkeypatch):
        """Regression test for bug #2: the command string is shell syntax
        but was previously run without shell=True, so it always failed."""
        CONFIG._adb = {"binary_path": "adb"}
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return type("R", (), {"returncode": 0, "stderr": ""})()

        monkeypatch.setattr(device.subprocess, "run", fake_run)
        device.cleanup_device_screenshots("dev1")

        assert len(calls) == 1
        cmd, kwargs = calls[0]
        assert kwargs.get("shell") is True
        assert cmd == "adb -s dev1 shell rm -f /sdcard/screen*.png"

    def test_nonzero_returncode_logs_warning_but_does_not_raise(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        monkeypatch.setattr(
            device.subprocess, "run",
            lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "denied"})(),
        )
        device.cleanup_device_screenshots("dev1")  # must not raise

    def test_exception_does_not_raise(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        monkeypatch.setattr(device.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        device.cleanup_device_screenshots("dev1")  # must not raise


# ---------------------------------------------------------------------------
# cleanup_temp_files - real filesystem via monkeypatch.chdir
# ---------------------------------------------------------------------------

class TestCleanupTempFiles:
    def test_removes_files_and_dirs_then_recreates_tmp(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tmp_dir = tmp_path / "tmp"
        tmp_dir.mkdir()
        (tmp_dir / "file.png").write_bytes(b"x")
        (tmp_dir / "subdir").mkdir()
        (tmp_dir / "subdir" / "nested.png").write_bytes(b"y")

        device.cleanup_temp_files()

        assert tmp_dir.exists()  # recreated in the finally block
        assert list(tmp_dir.iterdir()) == []

    def test_tmp_dir_missing_is_a_noop_and_recreates_it(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / "tmp").exists()
        device.cleanup_temp_files()
        assert (tmp_path / "tmp").exists()

    def test_undeletable_item_does_not_abort_cleanup(self, tmp_path, monkeypatch):
        """A single failed unlink/rmtree is caught per-item; cleanup still
        recreates tmp/ afterward rather than propagating."""
        monkeypatch.chdir(tmp_path)
        tmp_dir = tmp_path / "tmp"
        tmp_dir.mkdir()
        (tmp_dir / "ok.png").write_bytes(b"x")

        import pathlib
        original_unlink = pathlib.Path.unlink

        def flaky_unlink(self, *a, **k):
            if self.name == "ok.png":
                raise PermissionError("locked")
            return original_unlink(self, *a, **k)

        monkeypatch.setattr(pathlib.Path, "unlink", flaky_unlink)
        device.cleanup_temp_files()  # must not raise
        assert tmp_dir.exists()


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_calls_both_device_and_local_cleanup(self, monkeypatch):
        calls = []
        monkeypatch.setattr(device, "cleanup_device_screenshots", lambda device_id: calls.append(("device", device_id)))
        monkeypatch.setattr(device, "cleanup_temp_files", lambda: calls.append(("temp",)))
        device.cleanup("dev1")
        assert calls == [("device", "dev1"), ("temp",)]
