"""Interactive on-demand debug console, running alongside `python cli.py auto`.

Lets you type `capture` / `capture <template_name>` while automation keeps running,
to grab a screenshot for inspection without a debugger breakpoint. See CLAUDE.md
for the full command list.
"""

import os
import signal
import sys
import threading
from datetime import datetime
from typing import Optional

import cv2
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter
from prompt_toolkit.patch_stdout import patch_stdout

from .config import CONFIG
from .device import ensure_dir, pull_screenshot_to
from .image_processing import find_template_debug, _draw_match_overlay
from .logging import app_logger, console_handler

SCREENSHOTS_DIR = "screenshots"


def _request_process_shutdown() -> None:
    """Re-emit the equivalent OS signal for a real Ctrl+C, so the existing,
    unmodified SIGINT handler in cli.py runs exactly as it would from a genuine
    keypress - needed because prompt_toolkit's raw terminal mode intercepts
    Ctrl+C as a KeyboardInterrupt in the console thread instead of letting the
    OS deliver SIGINT normally."""
    if sys.platform == "win32":
        os.kill(0, signal.CTRL_C_EVENT)
    else:
        os.kill(os.getpid(), signal.SIGINT)


def _valid_template_names() -> list[str]:
    """Template names from config, excluding the 'device' key which selects a
    template folder override, not a template itself."""
    return [name for name in CONFIG['templates'].keys() if name != 'device']


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class InteractiveConsole:
    """Owns a background thread that reads commands from the terminal while
    the main automation loop keeps running, independent of MainAutomation."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self._thread: Optional[threading.Thread] = None
        self._original_stream = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="interactive-console")
        self._thread.start()

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
            if self._thread.is_alive():
                app_logger.debug("Interactive console thread did not exit within timeout")

    def _run(self) -> None:
        self._original_stream = console_handler.stream
        try:
            with patch_stdout():
                console_handler.setStream(sys.stdout)
                try:
                    self._run_loop()
                finally:
                    console_handler.setStream(self._original_stream)
        except Exception as e:
            app_logger.error(f"Interactive console error: {e}")

    def _run_loop(self) -> None:
        ensure_dir(SCREENSHOTS_DIR)

        completer = NestedCompleter.from_nested_dict({
            "capture": {name: None for name in _valid_template_names()},
            "help": None,
            "quit": None,
            "exit": None,
        })
        session = PromptSession(completer=completer)

        print("Interactive commands ready - type 'help' for the list, Tab to autocomplete.")

        while True:
            try:
                line = session.prompt("(capture) > ")
            except EOFError:
                _request_process_shutdown()
                break
            except KeyboardInterrupt:
                _request_process_shutdown()
                break

            try:
                if not self._dispatch(line):
                    break
            except Exception as e:
                app_logger.error(f"Error running interactive command: {e}")

    def _dispatch(self, line: str) -> bool:
        """Parse and run one command. Returns False if the console loop should stop."""
        parts = line.strip().split(maxsplit=1)
        if not parts:
            return True

        verb, rest = parts[0], (parts[1] if len(parts) > 1 else "")

        if verb in ("quit", "exit"):
            _request_process_shutdown()
            return False
        elif verb == "help":
            self._print_help()
        elif verb == "capture":
            template_name = rest.strip()
            if template_name:
                self._capture_template(template_name)
            else:
                self._capture_raw()
        else:
            print(f"Unknown command '{verb}'. Type 'help' for the list.")

        return True

    def _print_help(self) -> None:
        print("Commands:")
        print("  capture                 - save a raw screenshot now")
        print("  capture <template_name> - save a screenshot with a match overlay for that template")
        print("  help                    - show this message")
        print("  quit / exit             - stop the tool (same as Ctrl+C)")

    def _capture_raw(self) -> None:
        output_path = f"{SCREENSHOTS_DIR}/{_timestamp()}_capture.png"
        if pull_screenshot_to(self.device_id, output_path):
            print(f"Saved screenshot to {os.path.abspath(output_path)}")
        else:
            print("Failed to capture screenshot - check the log for details.")

    def _capture_template(self, template_name: str) -> None:
        valid_names = _valid_template_names()
        if template_name not in valid_names:
            print(f"Unknown template '{template_name}'. Valid names: {', '.join(sorted(valid_names))}")
            return

        raw_path = f"{SCREENSHOTS_DIR}/{_timestamp()}_capture.png"
        if not pull_screenshot_to(self.device_id, raw_path):
            print("Failed to capture screenshot - check the log for details.")
            return

        img = cv2.imread(raw_path)
        if img is None:
            print("Failed to read the captured screenshot back from disk.")
            return

        match = find_template_debug(self.device_id, template_name, existing_screenshot=img)
        if match is None:
            print(f"Error running template match for '{template_name}' - check the log for details.")
            return

        status = "MATCH" if match["found"] else "NOMATCH"
        overlay = _draw_match_overlay(img, match["top_left"], match["size"], match["confidence"])
        overlay_path = f"{SCREENSHOTS_DIR}/{_timestamp()}_capture_{template_name}_{status}_{match['confidence']:.3f}.png"
        cv2.imwrite(overlay_path, overlay)

        pass_fail = "PASS" if match["found"] else "FAIL"
        print(
            f"{template_name}: confidence={match['confidence']:.3f} "
            f"threshold={match['threshold']:.3f} [{pass_fail}]"
        )
        print(f"Saved to {os.path.abspath(overlay_path)}")
