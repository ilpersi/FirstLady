"""Configuration loading utilities"""

import json
from typing import Dict, Any
from pathlib import Path
from src.core.logging import app_logger


class ConfigManager:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self._config: Dict[str, Any] = {}
        self._automation_config: Dict[str, Any] = {}
        self._load_configs()

    def _load_configs(self) -> None:
        """Load all configuration files"""
        try:
            with open(self.config_dir / "config.json") as f:
                self._config = json.load(f)
            with open(self.config_dir / "automation.json") as f:
                self._automation_config = json.load(f)
        except Exception as e:
            app_logger.error(f"Error loading config: {e}")
            if not self._config:
                self._config = {}
            if not self._automation_config:
                self._automation_config = {}

        # Resolve once so repeated .control_list/.adb access (on nearly every
        # ADB call in the program) isn't rebuilding a default dict each time.
        self._control_list = self._config.get('control_list', {
            "whitelist": {"alliance": []},
            "blacklist": {"alliance": []}
        })
        self._adb = self._config.get('adb', {
            "host": "",
            "port": -1,
            "binary_path": "adb",
            "enforce_connection": False
        })

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access to main config"""
        return self._config.get(key, {})

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from main config with default"""
        return self._config.get(key, default)

    @property
    def time_checks(self) -> Dict[str, Any]:
        return self._automation_config.get("time_checks", {})

    @property
    def scheduled_events(self) -> Dict[str, Any]:
        return self._automation_config.get("scheduled_events", {})

    @property
    def debug_mode(self) -> bool:
        """Whether debug artifacts (overlay images, OCR crops) should be written to tmp/"""
        return bool(self._config.get('debug_mode', False))

    @property
    def control_list(self) -> Dict[str, Any]:
        """Get control list from main config"""
        return self._control_list

    @property
    def adb(self) -> Dict[str, Any]:
        return self._adb


# Create global instances
CONFIG = ConfigManager()
