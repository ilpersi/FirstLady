"""Tests for src.core.adb - mocks subprocess.run at src.core.adb.subprocess.run."""
import subprocess as real_subprocess

import pytest

import src.core.adb as adb
from src.core.config import CONFIG


# ---------------------------------------------------------------------------
# get_device_list
# ---------------------------------------------------------------------------

class TestGetDeviceList:
    def test_tcp_filtering_with_type_present(self, mock_subprocess_run):
        CONFIG._adb = {"host": "127.0.0.1", "port": 5555, "binary_path": "adb",
                        "enforce_connection": False, "type": "tcp"}

        def fake_run(cmd, **kwargs):
            mock_subprocess_run.calls.append(((cmd,), kwargs))
            if cmd[1] == "version":
                return type("R", (), {"stdout": "Android Debug Bridge version 1.0.41\n", "returncode": 0})()
            if cmd[1] == "devices":
                return type("R", (), {
                    "stdout": "List of devices attached\n127.0.0.1:5555\tdevice\nemulator-5554\tdevice\n",
                    "returncode": 0,
                })()
            raise AssertionError(f"unexpected cmd {cmd}")

        adb.subprocess.run = fake_run
        try:
            devices = adb.get_device_list()
        finally:
            adb.subprocess.run = real_subprocess.run
        assert devices == ["127.0.0.1:5555"]

    def test_type_missing_defaults_to_tcp_behavior(self, monkeypatch):
        """Regression test for bug #1: CONFIG.adb historically had no
        'type'/'serial' keys at all, which used to raise KeyError (silently
        swallowed, always returning [])."""
        CONFIG._adb = {"host": "127.0.0.1", "port": 5555, "binary_path": "adb",
                        "enforce_connection": False}
        assert "type" not in CONFIG._adb
        assert "serial" not in CONFIG._adb

        def fake_run(cmd, **kwargs):
            if cmd[1] == "version":
                return type("R", (), {"stdout": "Version 1.0.41\n", "returncode": 0})()
            if cmd[1] == "devices":
                return type("R", (), {
                    "stdout": "List of devices attached\n127.0.0.1:5555\tdevice\nemulator-5554\tdevice\n",
                    "returncode": 0,
                })()
            raise AssertionError(f"unexpected cmd {cmd}")

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        devices = adb.get_device_list()
        assert devices == ["127.0.0.1:5555"]

    def test_serial_filtering(self, monkeypatch):
        CONFIG._adb = {"host": "", "port": -1, "binary_path": "adb",
                        "enforce_connection": False, "type": "serial", "serial": "ABC123"}

        def fake_run(cmd, **kwargs):
            if cmd[1] == "version":
                return type("R", (), {"stdout": "Version 1.0.41\n", "returncode": 0})()
            if cmd[1] == "devices":
                return type("R", (), {
                    "stdout": "List of devices attached\nABC123\tdevice\nemulator-5554\tdevice\n",
                    "returncode": 0,
                })()
            raise AssertionError(f"unexpected cmd {cmd}")

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        devices = adb.get_device_list()
        assert devices == ["ABC123"]

    def test_no_devices_connected_returns_empty_list(self, monkeypatch):
        CONFIG._adb = {"host": "", "port": -1, "binary_path": "adb",
                        "enforce_connection": False, "type": "tcp"}

        def fake_run(cmd, **kwargs):
            if cmd[1] == "version":
                return type("R", (), {"stdout": "Version 1.0.41\n", "returncode": 0})()
            if cmd[1] == "devices":
                return type("R", (), {"stdout": "List of devices attached\n", "returncode": 0})()
            raise AssertionError(f"unexpected cmd {cmd}")

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        assert adb.get_device_list() == []

    def test_adb_not_found_falls_back_to_sdk_path_then_succeeds(self, monkeypatch):
        CONFIG._adb = {"host": "", "port": -1, "binary_path": "adb",
                        "enforce_connection": False, "type": "tcp"}

        calls = {"n": 0}

        def fake_run(cmd, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FileNotFoundError("adb not found")
            if cmd[1] == "version":
                return type("R", (), {"stdout": "Version 1.0.41\n", "returncode": 0})()
            if cmd[1] == "devices":
                return type("R", (), {"stdout": "List of devices attached\nemulator-5554\tdevice\n", "returncode": 0})()
            raise AssertionError(f"unexpected cmd {cmd}")

        def fake_exists(path):
            return path == "C:/Program Files/Android/platform-tools/adb.exe"

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        monkeypatch.setattr(adb.os.path, "exists", fake_exists)
        devices = adb.get_device_list()
        assert devices == ["emulator-5554"]
        assert CONFIG.adb["binary_path"] == "C:/Program Files/Android/platform-tools/adb.exe"

    def test_adb_not_found_anywhere_gives_up(self, monkeypatch):
        CONFIG._adb = {"host": "", "port": -1, "binary_path": "adb",
                        "enforce_connection": False, "type": "tcp"}

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("adb not found")

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        monkeypatch.setattr(adb.os.path, "exists", lambda path: False)
        assert adb.get_device_list() == []

    def test_general_exception_returns_empty_list(self, monkeypatch):
        CONFIG._adb = {"host": "", "port": -1, "binary_path": "adb",
                        "enforce_connection": False, "type": "tcp"}

        def fake_run(cmd, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        assert adb.get_device_list() == []


# ---------------------------------------------------------------------------
# launch_package / force_stop_package - no error handling at all
# ---------------------------------------------------------------------------

class TestLaunchAndForceStop:
    def test_launch_package_calls_monkey_command(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb)
        adb.launch_package("dev1", "com.fun.lastwar.gp")
        args, kwargs = mock_subprocess_run.calls[0]
        assert args[0] == ["adb", '-s', 'dev1', 'shell', 'monkey', '-p', 'com.fun.lastwar.gp',
                            '-c', 'android.intent.category.LAUNCHER', '1']
        assert kwargs["stdout"] == real_subprocess.DEVNULL
        assert kwargs["stderr"] == real_subprocess.DEVNULL

    def test_launch_package_propagates_exception(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}

        def fake_run(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError):
            adb.launch_package("dev1", "com.fun.lastwar.gp")

    def test_force_stop_package_calls_am_force_stop(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb)
        adb.force_stop_package("dev1", "com.fun.lastwar.gp")
        args, kwargs = mock_subprocess_run.calls[0]
        assert args[0] == ["adb", '-s', 'dev1', 'shell', 'am', 'force-stop', 'com.fun.lastwar.gp']

    def test_force_stop_package_propagates_exception(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}

        def fake_run(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError):
            adb.force_stop_package("dev1", "com.fun.lastwar.gp")


# ---------------------------------------------------------------------------
# press_back / tap_screen / swipe_screen
# ---------------------------------------------------------------------------

class TestSimpleInputCommands:
    def test_press_back_success(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb, returncode=0)
        assert adb.press_back("dev1") is True

    def test_press_back_nonzero_returncode(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb, returncode=1)
        assert adb.press_back("dev1") is False

    def test_press_back_exception_returns_false(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        monkeypatch.setattr(adb.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert adb.press_back("dev1") is False

    def test_tap_screen_success(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb, returncode=0)
        assert adb.tap_screen("dev1", 10, 20) is True
        args, _ = mock_subprocess_run.calls[0]
        assert args[0] == ["adb", "-s", "dev1", "shell", "input", "tap", "10", "20"]

    def test_tap_screen_failure(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb, returncode=1)
        assert adb.tap_screen("dev1", 10, 20) is False

    def test_tap_screen_exception_returns_false(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        monkeypatch.setattr(adb.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert adb.tap_screen("dev1", 1, 2) is False

    def test_swipe_screen_success(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb, returncode=0)
        assert adb.swipe_screen("dev1", 1, 2, 3, 4, duration=500) is True
        args, _ = mock_subprocess_run.calls[0]
        assert args[0] == ["adb", "-s", "dev1", "shell", "input", "swipe", "1", "2", "3", "4", "500"]

    def test_swipe_screen_failure(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb, returncode=1)
        assert adb.swipe_screen("dev1", 1, 2, 3, 4) is False

    def test_swipe_screen_exception_returns_false(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        monkeypatch.setattr(adb.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert adb.swipe_screen("dev1", 1, 2, 3, 4) is False


# ---------------------------------------------------------------------------
# get_connected_device
# ---------------------------------------------------------------------------

class TestGetConnectedDevice:
    def test_no_devices_returns_none(self, monkeypatch):
        monkeypatch.setattr(adb, "get_device_list", lambda: [])
        assert adb.get_connected_device() is None

    def test_one_device_returns_it(self, monkeypatch):
        monkeypatch.setattr(adb, "get_device_list", lambda: ["dev1"])
        assert adb.get_connected_device() == "dev1"

    def test_multiple_devices_returns_first_with_warning(self, monkeypatch):
        monkeypatch.setattr(adb, "get_device_list", lambda: ["dev1", "dev2"])
        assert adb.get_connected_device() == "dev1"


# ---------------------------------------------------------------------------
# get_current_running_app
# ---------------------------------------------------------------------------

class TestGetCurrentRunningApp:
    def test_mcurrentfocus_line_parsed(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        stdout = "  mCurrentFocus=Window{abc u0 com.fun.lastwar.gp/com.fun.lastwar.gp.MainActivity}\n"
        mock_subprocess_run.set_result(adb, stdout=stdout, returncode=0)
        assert adb.get_current_running_app("dev1") == "com.fun.lastwar.gp"

    def test_mfocusedapp_fallback_line_parsed(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        stdout = "  mFocusedApp=AppWindowToken{x token=Token{y ActivityRecord{z com.fun.lastwar.gp/.MainActivity t1}}}\n"
        mock_subprocess_run.set_result(adb, stdout=stdout, returncode=0)
        assert adb.get_current_running_app("dev1") == "com.fun.lastwar.gp"

    def test_recents_fallback_filters_to_recent_0_only(self, monkeypatch):
        """Regression test for bug #3: previously the unfiltered regex
        search could match any recent task, not just the foreground one."""
        CONFIG._adb = {"binary_path": "adb"}

        calls = {"n": 0}
        recents_stdout = (
            "ACTIVITY MANAGER RECENT TASKS (dumpsys activity recents)\n"
            "  Recent #0: TaskRecord{abc A=10123:com.expected.app U=0 sz=1}\n"
            "       taskId=1 effectiveUid=10123\n"
            "  Recent #1: TaskRecord{def A=10099:com.other.app U=0 sz=1}\n"
            "       taskId=2 effectiveUid=10099\n"
        )

        def fake_run(cmd, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                # window dump: no focus lines, forces the recents fallback
                return type("R", (), {"stdout": "irrelevant output\n", "returncode": 0})()
            assert cmd == ["adb", "-s", "dev1", "shell", "dumpsys", "activity", "recents"]
            return type("R", (), {"stdout": recents_stdout, "returncode": 0})()

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        assert adb.get_current_running_app("dev1") == "com.expected.app"

    def test_recents_fallback_no_match_returns_none(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        calls = {"n": 0}

        def fake_run(cmd, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return type("R", (), {"stdout": "irrelevant\n", "returncode": 0})()
            return type("R", (), {"stdout": "no recents at all\n", "returncode": 0})()

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        assert adb.get_current_running_app("dev1") is None

    def test_called_process_error_returns_none(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}

        def fake_run(cmd, **kwargs):
            raise real_subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        assert adb.get_current_running_app("dev1") is None


# ---------------------------------------------------------------------------
# long_press_screen
# ---------------------------------------------------------------------------

class TestLongPressScreen:
    def test_success_returns_true(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return type("R", (), {"returncode": 0})()

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        assert adb.long_press_screen("dev1", 10, 20, 1500) is True
        cmd, kwargs = calls[0]
        assert kwargs.get("shell") is True
        assert cmd == "adb -s dev1 shell input swipe 10 20 10 20 1500"

    def test_called_process_error_returns_false(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}

        def fake_run(cmd, **kwargs):
            raise real_subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        assert adb.long_press_screen("dev1", 10, 20, 1500) is False


# ---------------------------------------------------------------------------
# get_screen_size
# ---------------------------------------------------------------------------

class TestGetScreenSize:
    def test_parses_physical_size(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb, stdout="Physical size: 1080x1920\n", returncode=0)
        assert adb.get_screen_size("dev1") == (1080, 1920)

    def test_unparseable_output_raises_runtime_error(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb"}
        mock_subprocess_run.set_result(adb, stdout="nonsense output\n", returncode=0)
        with pytest.raises(RuntimeError):
            adb.get_screen_size("dev1")


# ---------------------------------------------------------------------------
# simulate_shake
# ---------------------------------------------------------------------------

class TestSimulateShake:
    def test_happy_path_returns_true(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}
        monkeypatch.setattr(adb.subprocess, "run", lambda *a, **k: None)
        monkeypatch.setattr(adb.time, "sleep", lambda s: None)
        assert adb.simulate_shake("dev1") is True

    def test_exception_returns_false(self, monkeypatch):
        CONFIG._adb = {"binary_path": "adb"}

        def fake_run(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(adb.subprocess, "run", fake_run)
        assert adb.simulate_shake("dev1") is False

    def test_duration_ms_scales_total_sleep(self, monkeypatch):
        """Regression test for bug #4: duration_ms was accepted but ignored."""
        CONFIG._adb = {"binary_path": "adb"}
        monkeypatch.setattr(adb.subprocess, "run", lambda *a, **k: None)

        sleeps = {"1000": [], "2000": []}

        def make_sleep(bucket):
            def fake_sleep(s):
                sleeps[bucket].append(s)
            return fake_sleep

        monkeypatch.setattr(adb.time, "sleep", make_sleep("1000"))
        adb.simulate_shake("dev1", duration_ms=1000)

        monkeypatch.setattr(adb.time, "sleep", make_sleep("2000"))
        adb.simulate_shake("dev1", duration_ms=2000)

        total_1000 = sum(sleeps["1000"])
        total_2000 = sum(sleeps["2000"])
        assert total_1000 > 0
        assert total_2000 == pytest.approx(total_1000 * 2)


# ---------------------------------------------------------------------------
# enforce_connection
# ---------------------------------------------------------------------------

class TestEnforceConnection:
    def test_disabled_makes_no_subprocess_call(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb", "host": "1.2.3.4", "port": 5555, "enforce_connection": False}
        mock_subprocess_run.set_result(adb)
        adb.enforce_connection()
        assert mock_subprocess_run.calls == []

    def test_enabled_with_host_and_port_calls_connect(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb", "host": "1.2.3.4", "port": 5555, "enforce_connection": True}
        mock_subprocess_run.set_result(adb)
        adb.enforce_connection()
        args, _ = mock_subprocess_run.calls[0]
        assert args[0] == ["adb", "connect", "1.2.3.4:5555"]

    def test_enabled_but_port_not_positive_makes_no_call(self, mock_subprocess_run):
        CONFIG._adb = {"binary_path": "adb", "host": "1.2.3.4", "port": 0, "enforce_connection": True}
        mock_subprocess_run.set_result(adb)
        adb.enforce_connection()
        assert mock_subprocess_run.calls == []
