# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python ADB-driven automation bot for the mobile game "Last War" (`com.fun.lastwar.gp`). It screenshots the
device/emulator, locates UI elements via OpenCV template matching (and Tesseract OCR for text like alliance
tags), and drives the game via `adb input tap/swipe`. There is no game API — everything is screen-scraping and
coordinate-based interaction, so changes to the game's UI (new app version, different resolution, different
device) can silently break template matches.

## Commands

```bash
pip install -r requirements.txt        # install dependencies (also needs Tesseract OCR installed separately, see README)

python cli.py auto                     # run the full automation loop (all enabled routines, forever)
python cli.py routine <name>           # run a single routine once, e.g. `python cli.py routine secretary`
python cli.py reset                    # force a game restart via ADB
python cli.py auto --debug             # verbose logging to logs/app.log
python cli.py auto --no-cleanup        # skip temp file / screenshot cleanup on exit
```

`<name>` for `routine` must be a key under `time_checks` in `config/automation.json` (only entries with a
non-null `interval` are valid — this list is computed at argparse setup time in `cli.py`).

There is no test suite, linter, or build step in this repo currently (`pytest`/`pytest-asyncio` are in
`requirements.txt` but no tests exist yet).

### Interactive debug console (`python cli.py auto` only)

While `auto` is running, a background `prompt_toolkit`-based console (`src/core/interactive_console.py`)
reads commands from the same terminal, independent of `MainAutomation`'s state:

```
capture                 # save a raw screenshot to screenshots/<timestamp>_capture.png
capture <template_name>  # screenshot + match overlay/confidence for one config/config.json template
help                    # list commands (Tab also autocompletes verbs and template names)
quit / exit             # stop the whole tool - same as Ctrl+C, not just the console
```

Output goes to the top-level `screenshots/` directory (gitignored), never `tmp/`, so it survives
`CleanupRoutine`'s hourly sweep. The console calls `pull_screenshot_to` (`src/core/device.py`) rather
than `take_screenshot`, so it never races the fixed `tmp/screen.png` every routine's template matching
reads. `quit`/`exit`, Ctrl+C, and Ctrl+D are all unified onto the same shutdown path: since
prompt_toolkit puts the terminal in raw mode while reading a line, a Ctrl+C keypress there becomes a
`KeyboardInterrupt` inside the console's own thread instead of a real OS signal, so
`_request_process_shutdown()` re-emits the equivalent signal (`SIGINT` on POSIX, a `CTRL_C_EVENT`
broadcast on Windows) so `cli.py`'s existing `signal_handler` still runs unmodified. The console also
rebinds `src/core/logging.py`'s `console_handler` to the patched stdout for its lifetime (and restores
it on exit) so log lines don't corrupt the prompt.

## Configuration (read before changing behavior)

Two JSON files drive everything; both are loaded once into a global `CONFIG` (`src/core/config.py`) at import
time — restart the process to pick up edits.

- `config/config.json` — package name, ADB connection (`adb.host`/`adb.port`/`adb.binary_path`, TCP or serial),
  emulator process-check/restart settings, all timing constants (`timings`), tap/swipe randomization
  (`randomization`), OCR settings, the alliance `control_list` whitelist/blacklist, Discord webhook message
  templates, and — critically — the `templates` map. Every template name used in code (e.g. `"help"`,
  `"accept"`, `"vacant-security"`) must have an entry here with a `path` (relative to
  `config/templates/<device>/`) and a per-template match `threshold`.
- `config/automation.json` — the routine registry, split into `time_checks` (interval-based, run when
  `now - last_run >= interval`) and `scheduled_events` (day+time based, UTC, ±5 minute window). Each entry maps
  a routine name to a `handler` (dotted class path) and either an `interval` (seconds) or a `schedule`
  (`day`/`time`). Setting `interval`/`day` to `null` disables a routine without deleting its config —
  prefer that over deleting entries.
- `config/templates/<device>/...` — PNG template images, organized by feature (`secretary/`, `alliance/`,
  `ui/`, `hidden_treasures/`). `CONFIG['templates']['device']` selects a device-specific override folder that
  falls back to `default/` per-image when a template is missing there (see `_load_template` in
  `image_processing.py`) — this is how the tool supports multiple screen resolutions/devices.
- Persisted run state lives in `state/automation_state.json` (created at runtime by `AutomationState`,
  `src/automation/state.py`) — last-run timestamps per routine, independent of the JSON config.
- Discord notifications (dig alerts, launch-failure alerts) require env vars (`.env` file):
  `DISCORD_WEBHOOK_URL`, `AUTOMATION_WEBHOOK_URL`.

## Architecture

**Entry point → orchestrator → routines**, with routines resolved dynamically by dotted-path string so new
routines never need to be wired into `cli.py`:

1. `cli.py` parses args, gets a connected device (`src/core/adb.py:get_connected_device`), and either runs one
   routine directly or builds a `MainAutomation` (`src/automation/automation.py`) and calls `.run()`/`.force_reset()`.
2. `MainAutomation` is the main loop (`start()` → `_run_automation_cycle()` in an infinite `while True`, called
   from `run()`). Each cycle: refresh due-ness of all checks/events (`src/core/scheduling.py`), verify the
   emulator process and the game app are running (relaunching via `src.game.controls.launch_game` /
   `navigate_home` with exponential backoff if not, capped and periodically Discord-notified), then
   `run_scheduled_tasks()`.
3. `run_scheduled_tasks()` computes `get_ordered_tasks()` — all due time_checks and scheduled_events sorted by
   how overdue they are (scheduled_events always sort first via `float('inf')`) — and runs them one at a time.
   Handlers are lazily created and cached per handler-path via `HandlerFactory`
   (`src/automation/handler_factory.py`), which introspects whether the target class subclasses
   `TimeCheckRoutine` to decide what constructor args to pass. On failure of a task, `MainAutomation` attempts
   one `reset_game()` + retry before giving up for that cycle. Successful runs update both the in-memory dict
   and `AutomationState` (persisted to disk immediately).
4. **Routine class hierarchy** (`src/automation/routines/routineBase.py`): `RoutineBase` (ABC) defines the
   `start()` template method — it forces navigation home first (unless `automation.game_state["is_home"]` is
   already `True`), then calls the subclass's `_execute()`; also defines `should_run()`/`after_run()` as
   abstract. `TimeCheckRoutine` implements interval-based `should_run`/`after_run`. `DailyRoutine` implements
   day+time based scheduling (used for `scheduled_events`, e.g. `weekly_reset` — note this handler is currently
   commented out in `routines/__init__.py` and disabled via `null` day in `automation.json`). Every concrete
   routine (`secretary.py`, `help.py`, `checkForDigs.py`, `mapExchange.py`, `allianceDonate.py`,
   `allianceGifts.py`, `collectResources.py`, `cleanup.py`) implements only `_execute()`, typically delegating
   to `execute_with_error_handling(self._some_internal_method)` for uniform exception logging. Routines that
   navigate away from the home screen must set `self.automation.game_state["is_home"] = False` themselves —
   nothing else clears that flag.
5. **Screen interaction stack**, bottom to top:
   - `src/core/adb.py` — raw ADB subprocess calls (tap, swipe, long-press-via-swipe, back, launch/force-stop
     package, device discovery honoring `adb.type` == `tcp`/`serial` for targeting a specific device, shake
     simulation via sensor props).
   - `src/core/device.py` — screenshot capture (`adb exec-out screencap` piped to `tmp/screen.png`) and
     temp/device cleanup.
   - `src/core/image_processing.py` — template matching on top of screenshots: `find_template` (best single
     match above threshold), `find_all_templates` (repeated match + non-max suppression, optionally scoped to
     a `search_region`), `wait_for_image` (poll with timeout), `find_and_tap_template` (find + humanized tap,
     the primary building block almost every routine calls). Templates are cached in memory after first load
     (`_load_template`), and all of these accept an optional `existing_screenshot` to reuse one screenshot
     across several checks instead of re-capturing. Debug overlay images are only written when
     `CONFIG.debug_mode` is true (default off); `find_template_debug` returns match details unconditionally
     for the interactive console below, without writing anything itself.
   - `src/core/text_detection.py` — OCR path used specifically for reading alliance tags next to the secretary
     "accept" button: locates bracket templates to bound the text region, crops/upscales/binarizes, then runs
     Tesseract with a whitelist-aware config. Whitelist/blacklist comparisons are exact-string against
     `CONTROL_LIST` (from `config.json` `control_list`), so OCR misreads directly cause wrong
     accept/reject decisions — see the OCR caveats in README (`O`/`0`, `S`/`s`, etc.).
   - `src/game/controls.py` — the humanized layer: `human_delay` (sleep scaled by `sleep_multiplier`),
     `humanized_tap`/`humanized_long_press` (adds random jitter from `randomization.normal_radius` /
     `critical_radius`), `handle_swipes` (scroll with randomized start/end and duration), `launch_game`,
     `navigate_home` (press-back loop until the home template is found, handling stray "quit" dialogs).
6. **Discord integration** (`src/core/discord_bot.py`, used by `checkForDigs.py` and launch-failure alerts in
   `automation.py`) is best-effort and gated on the relevant webhook env var being set; routines must keep
   working with Discord disabled.

## Conventions when adding a new routine

- Put the file in `src/automation/routines/`, subclass `TimeCheckRoutine` (interval-based) or `DailyRoutine`
  (day/time-based), implement `_execute()` only (wrap real logic in `execute_with_error_handling`).
- Add every new template image + threshold to `config/config.json` under `templates` before referencing its
  name in `find_template`/`find_and_tap_template`/`find_all_templates` — a missing entry logs an error and the
  call returns `None`/`[]` rather than raising, so failures can silently no-op if you forget this.
- Register the routine's dotted handler path under `time_checks` or `scheduled_events` in
  `config/automation.json`; it does not need to be imported in `routines/__init__.py` (that file only
  re-exports a few classes for convenience elsewhere), but `HandlerFactory` does need the module to be
  importable via `importlib.import_module`.
- If the routine navigates away from the home screen, set `self.automation.game_state["is_home"] = False` at
  the start, mirroring existing routines — otherwise `RoutineBase.start()` won't re-navigate home before your
  routine runs on a stale assumption.
- Use `humanized_tap`/`humanized_long_press`/`handle_swipes` rather than calling `src.core.adb` tap/swipe
  functions directly, to keep randomized timing/positioning consistent across routines.
