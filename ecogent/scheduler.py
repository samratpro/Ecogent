"""
Periodic task execution for Automation chats (schedules.json in the home folder).
Due runs are handed to the worker queue, so they never overlap with other work.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .storage import read_json, write_json


_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def validate_rule(every_minutes=None, daily_at: str = "") -> tuple[Optional[int], Optional[str]]:
    """Normalized (every_minutes, daily_at); raises ValueError for anything unusable."""
    if every_minutes not in (None, "", 0):
        try:
            minutes = int(every_minutes)
        except (TypeError, ValueError):
            raise ValueError(f"every_minutes must be a number, got {every_minutes!r}") from None
        if minutes < 1:
            raise ValueError("every_minutes must be at least 1")
        return minutes, None
    m = _HHMM.match(str(daily_at or "").strip())
    if not m:
        raise ValueError(f"daily time must be HH:MM (00:00-23:59), got {daily_at!r}")
    return None, f"{int(m.group(1)):02d}:{m.group(2)}"


def next_run(entry: dict, after: Optional[datetime] = None) -> str:
    now = after or datetime.now()
    if entry.get("every_minutes"):
        return (now + timedelta(minutes=max(1, int(entry["every_minutes"])))).isoformat(timespec="seconds")
    hh, mm = (entry.get("daily_at") or "09:00").split(":")[:2]
    t = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if t <= now:
        t += timedelta(days=1)
    return t.isoformat(timespec="seconds")


def describe(entry: dict) -> str:
    return f"every {entry['every_minutes']} min" if entry.get("every_minutes") else f"daily at {entry.get('daily_at')}"


class Scheduler(threading.Thread):
    def __init__(self, path: Path, on_due: Callable[[str], None], interval_s: int = 20):
        super().__init__(daemon=True, name="ecogent-scheduler")
        self.path = Path(path)
        self.on_due = on_due
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ store
    def entries(self) -> list[dict]:
        return read_json(self.path, [])

    def _save(self, entries: list[dict]) -> None:
        write_json(self.path, entries)

    def add(self, chat_id: str, title: str, every_minutes: Optional[int] = None, daily_at: str = "") -> None:
        every_minutes, daily_at = validate_rule(every_minutes, daily_at)
        with self._lock:
            entries = [e for e in self.entries() if e["chat_id"] != chat_id]
            entry = {"chat_id": chat_id, "title": title, "every_minutes": every_minutes,
                     "daily_at": daily_at, "enabled": True, "last_run": None}
            entry["next_run"] = next_run(entry)
            entries.append(entry)
            self._save(entries)

    def remove(self, chat_id: str) -> None:
        with self._lock:
            self._save([e for e in self.entries() if e["chat_id"] != chat_id])

    def toggle(self, chat_id: str) -> None:
        with self._lock:
            entries = self.entries()
            for e in entries:
                if e["chat_id"] == chat_id:
                    e["enabled"] = not e.get("enabled", True)
                    if e["enabled"]:
                        e["next_run"] = next_run(e)
            self._save(entries)

    # ------------------------------------------------------------------ loop
    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(self.interval_s):
            due = []
            with self._lock:
                entries = self.entries()
                now = datetime.now()
                changed = False
                for e in entries:
                    try:
                        if e.get("enabled", True) and e.get("next_run") and datetime.fromisoformat(e["next_run"]) <= now:
                            e["last_run"] = now.isoformat(timespec="seconds")
                            e["next_run"] = next_run(e, now)
                            due.append(e["chat_id"])
                            changed = True
                    except (ValueError, TypeError, KeyError):
                        e["enabled"] = False      # broken entry: disable it, keep the scheduler running
                        changed = True
                if changed:
                    self._save(entries)
            for chat_id in due:
                self.on_due(chat_id)
