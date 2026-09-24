"""Device interaction utilities"""

import subprocess

from .logging import app_logger
from pathlib import Path
import shutil
from src.core.config import CONFIG

def take_screenshot(device_id: str) -> bool:
    """Take screenshot and pull to local tmp directory"""
    try:
        ensure_dir("tmp")

        cmd = [CONFIG.adb["binary_path"], "exec-out", "screencap","-p"]
        with open('tmp/screen.png', "w") as outfile:
            result =  subprocess.run(cmd, stdout=outfile)
            if result.returncode != 0:
                app_logger.error(f"Failed to pull screenshot: {result.stderr}")
                return False

        return True

    except Exception as e:
        app_logger.error(f"Error taking screenshot: {e}")
        return False

def cleanup_device_screenshots(device_id: str) -> None:
    """Clean up screenshots from device"""
    try:
        cmd = f"{CONFIG.adb['binary_path']} -s {device_id} shell rm -f /sdcard/screen*.png"
        result = subprocess.run(cmd, capture_output=True, text=True)
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

def cleanup(device_id: str) -> None:
    """Cleanup device and local temp files"""
    cleanup_device_screenshots(device_id)
    cleanup_temp_files()

def ensure_dir(path: str) -> None:
    """Ensure directory exists"""
    Path(path).mkdir(exist_ok=True)