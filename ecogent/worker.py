"""
Worker thread: all agent and browser work runs here, one job at a time
(Playwright's sync API must stay on a single thread).
"""

from __future__ import annotations

import queue
import threading
import traceback
from typing import Any, Callable

from .bridge import UIBridge
from .config import Settings
from .core import EcogentAgent


class Worker(threading.Thread):
    def __init__(self, settings: Settings, ui: UIBridge):
        super().__init__(daemon=True, name="ecogent-worker")
        self.ui = ui
        self.stop_event = threading.Event()
        self.agent = EcogentAgent(settings, ui, self.stop_event)
        self.jobs: "queue.Queue[tuple[str, Callable, tuple] | None]" = queue.Queue()
        self.busy = False

    def submit(self, label: str, fn: Callable[..., Any], *args) -> None:
        self.jobs.put((label, fn, args))
        if self.busy:
            self.ui.log(f"Queued: {label}")

    def cancel(self) -> None:
        self.stop_event.set()
        self.ui.cancel_event.set()   # releases any dialog the agent is waiting on

    def shutdown(self) -> None:
        self.cancel()
        with self.jobs.mutex:
            self.jobs.queue.clear()
        self.jobs.put(None)

    def run(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                break
            label, fn, args = job
            self.stop_event.clear()
            self.ui.cancel_event.clear()
            self.busy = True
            self.ui.emit("busy", busy=True, label=label)
            try:
                fn(*args)
            except Exception as e:
                self.ui.log(f"{label} failed: {e}\n{traceback.format_exc()}")
                self.ui.emit("error", text=f"{label} failed: {e}")
            finally:
                self.busy = False
                self.ui.emit("busy", busy=False, label=label)
        try:
            self.agent.browser.close()
        except Exception:
            pass
