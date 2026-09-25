"""A minimal DailyRoutine subclass importable via a dotted path, used to
exercise HandlerFactory's non-TimeCheckRoutine construction branch and
DailyRoutine's own automation-passthrough behavior (regression coverage for
bug #12) without needing a real disabled routine like weeklyReset.py (which
does not exist on disk - see config/automation.json's weekly_reset entry)."""
from src.automation.routines.routineBase import DailyRoutine


class DummyDailyRoutine(DailyRoutine):
    def __init__(self, device_id, day="monday", time="00:00", automation=None):
        super().__init__(device_id, day, time, automation=automation)
        self.executed = False

    def _execute(self) -> bool:
        self.executed = True
        return True
