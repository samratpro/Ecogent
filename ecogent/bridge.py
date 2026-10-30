"""
Bridge between the agent (worker thread) and the user interface.

The agent calls blocking methods such as hold() or confirm_sample(); the GUI shows a
dialog and answers. HeadlessBridge answers automatically for CLI / tool-call use.
"""

from __future__ import annotations

import itertools
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class UIEvent:
    kind: str                       # log | message | files | chats | status | usage | request | busy
    chat_id: str = ""
    payload: dict = field(default_factory=dict)


class UIBridge:
    def __init__(self, events: "queue.Queue[UIEvent]"):
        self.events = events
        self._pending: dict[int, tuple[threading.Event, list]] = {}
        self._ids = itertools.count(1)
        self.cancel_event = threading.Event()

    # ------------------------------------------------------------------ fire and forget
    def emit(self, kind: str, chat_id: str = "", **payload) -> None:
        self.events.put(UIEvent(kind, chat_id, payload))

    def log(self, text: str, chat_id: str = "") -> None:
        self.emit("log", chat_id, text=text)

    def message(self, chat_id: str, role: str, text: str) -> None:
        self.emit("message", chat_id, role=role, text=text)

    # ------------------------------------------------------------------ blocking requests
    def request(self, kind: str, chat_id: str = "", **payload) -> Any:
        req_id = next(self._ids)
        done, box = threading.Event(), []
        self._pending[req_id] = (done, box)
        self.emit("request", chat_id, req_id=req_id, req_kind=kind, **payload)
        while not done.wait(0.25):
            if self.cancel_event.is_set():
                self._pending.pop(req_id, None)
                return None
        self._pending.pop(req_id, None)
        return box[0] if box else None

    def respond(self, req_id: int, value: Any) -> None:
        pending = self._pending.get(req_id)
        if pending:
            pending[1].append(value)
            pending[0].set()

    def hold(self, chat_id: str, message: str) -> bool:
        """Pause for the human (captcha, login, credentials). True = continue."""
        return bool(self.request("hold", chat_id, message=message))

    def confirm(self, chat_id: str, message: str) -> bool:
        return bool(self.request("confirm", chat_id, message=message))

    def confirm_sample(self, chat_id: str, rows: list[dict], note: str = "") -> tuple[bool, str]:
        ans = self.request("sample", chat_id, rows=rows, note=note) or {}
        return bool(ans.get("ok")), ans.get("comment", "")

    def ask_user_info(self, chat_id: str, fields: list[str], message: str = "") -> Optional[dict]:
        return self.request("user_info", chat_id, fields=fields, message=message)

    def choose(self, chat_id: str, message: str, options: list[str], default: str = "") -> Optional[str]:
        return self.request("choose", chat_id, message=message, options=options, default=default)


class HeadlessBridge(UIBridge):
    """No human attached: never blocks, refuses anything that needs a person."""

    def __init__(self, printer=print):
        super().__init__(queue.Queue())
        self.printer = printer

    def emit(self, kind: str, chat_id: str = "", **payload) -> None:
        if kind == "log":
            self.printer(payload.get("text", ""))
        elif kind == "message":
            self.printer(f"[{payload.get('role')}] {payload.get('text')}")

    def request(self, kind: str, chat_id: str = "", **payload) -> Any:
        if kind == "sample":
            return {"ok": True, "comment": ""}       # LLM validation already passed
        if kind == "choose":
            return payload.get("default")
        self.printer(f"[needs user, skipped] {payload.get('message', kind)}")
        return None
