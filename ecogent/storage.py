"""
Per-chat workspace (the "chat NoSQL" store).

<home>/chats/<chat_id>/
    plan.json          goal, destination, execution memory, data, runs
    current_task.json  steps the agent executes
    steps.json         execution log
    chat.json          meta, messages, memory summary, token usage
    user_info.json     facts the user provided for automation (optional)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return s[:limit] or "chat"


def read_json(path: Path, default: Any) -> Any:
    with _lock:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default


def write_json(path: Path, data: Any) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        for _ in range(5):  # Windows: the GUI may be reading the file at this moment
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05)
        os.replace(tmp, path)


class ChatSession:
    def __init__(self, folder: Path, temp_root: Path, output_root: Path):
        self.folder = Path(folder)
        self.id = self.folder.name
        self.temp_dir = Path(temp_root) / self.id
        self._output_root = Path(output_root)

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    def create(cls, chats_dir: Path, temp_root: Path, output_root: Path, task_type: str,
               title: str = "", profile: str = "", headless: bool = False) -> "ChatSession":
        chat_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
        s = cls(Path(chats_dir) / chat_id, temp_root, output_root)
        s.folder.mkdir(parents=True, exist_ok=True)
        write_json(s.chat_path, {
            "meta": {
                "id": chat_id,
                "title": title or "New task",
                "task_type": task_type,
                "status": "new",
                "profile": profile,
                "headless": headless,
                "user_info_file": "",
                "work_folder": "",
                "created": now_iso(),
                "updated": now_iso(),
            },
            "summary": "",
            "messages": [],
            "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "by_purpose": {}},
        })
        write_json(s.plan_path, {})
        write_json(s.task_path, [])
        write_json(s.steps_path, [])
        return s

    @classmethod
    def list_all(cls, chats_dir: Path) -> list[dict]:
        out = []
        if not Path(chats_dir).exists():
            return out
        for d in sorted(Path(chats_dir).iterdir(), reverse=True):
            meta = read_json(d / "chat.json", {}).get("meta")
            if meta:
                out.append(meta)
        return out

    def delete(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------ paths
    @property
    def plan_path(self) -> Path:
        return self.folder / "plan.json"

    @property
    def task_path(self) -> Path:
        return self.folder / "current_task.json"

    @property
    def steps_path(self) -> Path:
        return self.folder / "steps.json"

    @property
    def chat_path(self) -> Path:
        return self.folder / "chat.json"

    @property
    def user_info_path(self) -> Path:
        return self.folder / "user_info.json"

    @property
    def output_dir(self) -> Path:
        d = self._output_root / f"{slugify(self.meta.get('title', ''))}_{self.id[-4:]}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ensure_temp(self) -> Path:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        return self.temp_dir

    # ------------------------------------------------------------------ plan / task
    @property
    def plan(self) -> dict:
        return read_json(self.plan_path, {})

    def save_plan(self, plan: dict) -> None:
        write_json(self.plan_path, plan)

    @property
    def current_task(self) -> list:
        return read_json(self.task_path, [])

    def save_task(self, steps: list) -> None:
        write_json(self.task_path, steps)

    def log_step(self, entry: dict) -> None:
        with _lock:
            log = read_json(self.steps_path, [])
            log.append({"time": now_iso(), **entry})
            write_json(self.steps_path, log[-2000:])

    # ------------------------------------------------------------------ chat memory
    @property
    def chat(self) -> dict:
        return read_json(self.chat_path, {"meta": {}, "messages": [], "summary": "", "usage": {}})

    @property
    def meta(self) -> dict:
        return self.chat.get("meta", {})

    def update_meta(self, **kw) -> None:
        with _lock:
            c = self.chat
            c["meta"].update(kw, updated=now_iso())
            write_json(self.chat_path, c)

    def add_message(self, role: str, text: str) -> None:
        with _lock:
            c = self.chat
            c["messages"].append({"role": role, "text": text, "time": now_iso()})
            write_json(self.chat_path, c)

    def set_summary(self, summary: str) -> None:
        if not summary:
            return
        with _lock:
            c = self.chat
            c["summary"] = summary
            write_json(self.chat_path, c)

    def add_usage(self, purpose: str, provider: str, model: str, tin: int, tout: int) -> None:
        with _lock:
            c = self.chat
            u = c.setdefault("usage", {"calls": 0, "input_tokens": 0, "output_tokens": 0, "by_purpose": {}})
            u["calls"] = u.get("calls", 0) + 1
            u["input_tokens"] = u.get("input_tokens", 0) + tin
            u["output_tokens"] = u.get("output_tokens", 0) + tout
            p = u.setdefault("by_purpose", {}).setdefault(purpose, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            p["calls"] += 1
            p["input_tokens"] += tin
            p["output_tokens"] += tout
            p["model"] = f"{provider}:{model}"
            write_json(self.chat_path, c)

    @property
    def usage(self) -> dict:
        return self.chat.get("usage", {})

    # ------------------------------------------------------------------ user info
    def user_info(self) -> dict:
        info = read_json(self.user_info_path, {})
        ext = self.meta.get("user_info_file")
        if ext and Path(ext).exists():
            p = Path(ext)
            if p.suffix.lower() == ".json":
                extra = read_json(p, {})
                if isinstance(extra, dict):
                    info = {**extra, **info}
            else:
                info.setdefault("text", p.read_text(encoding="utf-8", errors="replace"))
        return info

    def save_user_info(self, info: dict) -> None:
        write_json(self.user_info_path, info)


def open_session(settings, chat_id: str) -> Optional[ChatSession]:
    folder = settings.chats_path / chat_id
    if not folder.exists():
        return None
    return ChatSession(folder, settings.temp_path, settings.output_path)
