"""Device interaction utilities"""

import subprocess
from typing import Optional

from .logging import app_logger
from pathlib import Path
import shutil
from src.core.config import CONFIG

def ensure_dir(path: str) -> None:
    """Ensure directory exists"""
    Path(path).mkdir(exist_ok=True)

# tmp/ must always exist for CONFIG.debug_mode-gated writes elsewhere (which
# no longer get it created as a side effect of every screenshot capture, now
# that the internal matching pipeline captures in memory - see
# capture_screenshot_bytes below). Mirrors logs/ being created the same way
# at import time in src/core/logging.py.
ensure_dir("tmp")

def capture_screenshot_bytes(device_id: str) -> Optional[bytes]:
    """Pull a screenshot straight into memory - no disk round-trip. For
    callers that only need to decode it once (the internal template-matching
    pipeline via _take_and_load_screenshot in image_processing.py) rather
    than needing a persisted file (that's what pull_screenshot_to/
    take_screenshot are for, e.g. the interactive on-demand capture console,
    where producing an actual file is the point)."""
    try:
        cmd = [CONFIG.adb["binary_path"], "-s", device_id, "exec-out", "screencap", "-p"]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            app_logger.error(f"Failed to capture screenshot: {result.stderr}")
            return None
        return result.stdout

    except Exception as e:
        app_logger.error(f"Error capturing screenshot: {e}")
        return None

def pull_screenshot_to(device_id: str, output_path: str) -> bool:
    """Pull a screenshot to a caller-supplied path. `take_screenshot` is a thin
    wrapper around this for the shared `tmp/screen.png` target - a caller that
    needs its own distinct file (e.g. a concurrent on-demand capture that must
    not race whatever the main automation loop is doing with that shared file)
    should call this directly instead."""
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = [CONFIG.adb["binary_path"], "-s", device_id, "exec-out", "screencap", "-p"]
        with open(output_path, "wb") as outfile:
            result = subprocess.run(cmd, stdout=outfile)
            if result.returncode != 0:
                app_logger.error(f"Failed to pull screenshot to {output_path}: {result.stderr}")
                return False

        return True

    except Exception as e:
        app_logger.error(f"Error pulling screenshot to {output_path}: {e}")
        return False

def take_screenshot(device_id: str) -> bool:
    """Take screenshot and pull to local tmp/screen.png"""
    return pull_screenshot_to(device_id, "tmp/screen.png")

def cleanup_device_screenshots(device_id: str) -> None:
    """Clean up screenshots from device"""
    try:
        cmd = f"{CONFIG.adb['binary_path']} -s {device_id} shell rm -f /sdcard/screen*.png"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            app_logger.debug("Cleaned up device screenshots")
        else:
            app_logger.warning(f"Failed to clean device screenshots: {result.stderr}")
    except Exception as e:
        app_logger.error(f"Error cleaning device screenshots: {e}")

def cleanup_temp_files() -> None:
    """Clean up temporary files"""
    try:
        # Remove entire tmp directory and its contents recursively
        tmp_dir = Path("tmp")
        if tmp_dir.exists():
            for item in tmp_dir.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                        app_logger.debug(f"Cleaned up temporary file: {item}")
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                        app_logger.debug(f"Cleaned up temporary directory: {item}")
                except Exception as e:
                    app_logger.warning(f"Failed to delete {item}: {e}")
            
            try:
                tmp_dir.rmdir()
                app_logger.debug("Cleaned up main temporary directory")
            except Exception as e:
                app_logger.warning(f"Failed to delete tmp directory: {e}")
    except Exception as e:
        app_logger.error(f"Error cleaning temporary files: {e}")
    finally:
        # Recreate it immediately so it's always available for the next
        # CONFIG.debug_mode-gated write, regardless of what ran above.
        ensure_dir("tmp")

def cleanup(device_id: str) -> None:
    """Cleanup device and local temp files"""
    cleanup_device_screenshots(device_id)
    cleanup_temp_files()