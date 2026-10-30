"""
Ecogent desktop GUI (DearPyGui) - modern web-dashboard style.

Header: brand, status pill, run controls. Sidebar: new task, search, task cards, token stats.
Main card: chat bubbles + composer, plan.json / current_task.json / steps.json / chat.json,
files. Bottom card: activity log.
All agent work runs on the Worker thread; the render loop only reacts to UIEvents.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
from pathlib import Path
from typing import Optional

import dearpygui.dearpygui as dpg

from ..bridge import UIBridge, UIEvent
from ..config import PROVIDERS, TASK_LABELS, TASK_TYPES, Settings
from ..scheduler import Scheduler
from ..storage import ChatSession, open_session, read_json, write_json
from ..worker import Worker
from . import dialogs
from . import style as st

JSON_TABS = [("plan", "plan.json", "Plan", True), ("task", "current_task.json", "Current task", True),
             ("steps", "steps.json", "Steps", False), ("memory", "chat.json", "Memory", False)]
MAX_LOG_LINES = 400
BUBBLE_INDENT = 140


def open_path(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        return
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606 - user-initiated open of their own file
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class _StdoutToLog:
    """Show BrowserManager's print() output in the activity log."""

    def __init__(self, events: queue.Queue, original):
        self.events, self.original = events, original

    def write(self, s: str) -> int:
        if s and s.strip():
            self.events.put(UIEvent("log", payload={"text": s.rstrip()}))
        if self.original:
            try:
                self.original.write(s)
            except Exception:
                pass
        return len(s or "")

    def flush(self) -> None:
        if self.original:
            try:
                self.original.flush()
            except Exception:
                pass


class EcogentApp:
    def __init__(self):
        self.settings = Settings.load()
        self.events: "queue.Queue[UIEvent]" = queue.Queue()
        self.ui = UIBridge(self.events)
        self.worker = Worker(self.settings, self.ui)
        self.worker.agent.on_schedule = self._schedule_from_agent
        self.worker.start()
        self.scheduler = Scheduler(self.settings.schedules_file, self._scheduled_due)
        self.scheduler.start()
        self.current: Optional[str] = None
        self.request_dialogs: list[dialogs.Dialog] = []
        self.json_dirty = {key: False for key, *_ in JSON_TABS}
        self.json_path: dict[str, Optional[Path]] = {key: None for key, *_ in JSON_TABS}
        self._scroll_chat = 0
        self._scroll_log = 0

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        with dpg.window(tag="main", no_scrollbar=True):
            self._build_header()
            with dpg.group(horizontal=True):
                self._build_sidebar()
                with dpg.group():
                    with dpg.child_window(tag="main_card", height=-196, border=True):
                        dpg.bind_item_theme(dpg.last_item(), "card")
                        with dpg.tab_bar():
                            with dpg.tab(label="  Chat  "):
                                self._build_chat()
                            for key, filename, label, editable in JSON_TABS:
                                with dpg.tab(label=f"  {label}  "):
                                    self._build_json_tab(key, filename, editable)
                            with dpg.tab(label="  Files  "):
                                with dpg.group(horizontal=True):
                                    dpg.bind_item_theme(dpg.add_button(label="Refresh", callback=self._load_files), "btn_secondary")
                                    dpg.bind_item_theme(dpg.add_button(label="Open output folder", callback=self.open_output), "btn_ghost")
                                dpg.add_child_window(tag="files_list", border=False)
                                dpg.bind_item_theme(dpg.last_item(), "flat")
                    with dpg.child_window(height=-1, border=True):
                        dpg.bind_item_theme(dpg.last_item(), "card")
                        with dpg.group(horizontal=True):
                            st.section_label("Activity")
                            st.font(dpg.add_text("browser, LLM and step events", color=st.FAINT), "small")
                        dpg.add_child_window(tag="log_view", height=-1, border=False)
                        dpg.bind_item_theme(dpg.last_item(), "flat")

    def _build_header(self) -> None:
        with dpg.child_window(tag="header_bar", height=70, border=True, no_scrollbar=True):
            dpg.bind_item_theme(dpg.last_item(), "header")
            with dpg.group(horizontal=True):
                logo = dpg.add_button(label="E", width=38, height=38)
                dpg.bind_item_theme(logo, "btn_primary")
                st.font(logo, "h2")
                with dpg.group():
                    st.font(dpg.add_text("Ecogent"), "title")
            with dpg.group(tag="header_sub", horizontal=True):
                st.font(dpg.add_text("token-efficient browser agent", color=st.FAINT), "small")
            with dpg.group(tag="header_right", horizontal=True):
                dpg.add_loading_indicator(tag="spinner", style=1, radius=1.3, show=False,
                                          color=st.PRIMARY_HOVER, secondary_color=st.SURFACE_2)
                dpg.add_button(tag="status", label="Ready")
                dpg.bind_item_theme("status", "pill_ok")
                dpg.add_spacer(width=6)
                dpg.bind_item_theme(dpg.add_button(label="Run again", callback=self.run_again), "btn_secondary")
                dpg.bind_item_theme(dpg.add_button(tag="stop_btn", label="Stop", callback=self.stop, enabled=False), "btn_danger")
                dpg.add_spacer(width=6)
                for label, cb in (("Profiles", self.open_profiles), ("Schedules", self.open_schedules),
                                  ("Output", self.open_output), ("Settings", self.open_settings)):
                    dpg.bind_item_theme(dpg.add_button(label=label, callback=cb), "btn_ghost")

    def _build_sidebar(self) -> None:
        with dpg.child_window(width=300, height=-1, border=True, no_scrollbar=True):
            dpg.bind_item_theme(dpg.last_item(), "sidebar")
            b = dpg.add_button(label="+   New task", width=-1, height=42, callback=lambda: self.new_task())
            dpg.bind_item_theme(b, "btn_primary")
            st.font(b, "semibold")
            dpg.add_input_text(tag="task_search", hint="Search tasks...", width=-1,
                               callback=lambda: self.refresh_chats())
            st.section_label("Tasks")
            dpg.add_child_window(tag="chat_list", height=-258, border=False)
            dpg.bind_item_theme(dpg.last_item(), "flat")
            dpg.add_separator()
            st.section_label("This task")
            with dpg.group(horizontal=True):
                self._stat("usage_in", "Tokens in")
                self._stat("usage_out", "Tokens out")
            with dpg.group(horizontal=True):
                self._stat("usage_calls", "LLM calls")
                self._stat("usage_hits", "Cache hits")
            d = dpg.add_button(label="Delete task", width=-1, callback=self.delete_chat)
            dpg.bind_item_theme(d, "btn_ghost")

    def _stat(self, tag: str, label: str) -> None:
        with dpg.child_window(width=128, height=80, border=True, no_scrollbar=True):
            dpg.bind_item_theme(dpg.last_item(), "tile")
            st.font(dpg.add_text(label, color=st.FAINT), "small")
            st.font(dpg.add_text("-", tag=tag), "stat")

    def _build_chat(self) -> None:
        with dpg.group(horizontal=True):
            dpg.add_button(tag="chat_type", label="No task selected")
            dpg.bind_item_theme("chat_type", "pill_info")
            dpg.add_combo(["(temporary profile)"], tag="chat_profile", width=210,
                          default_value="(temporary profile)", callback=self._profile_changed)
            with dpg.tooltip("chat_profile"):
                dpg.add_text("Browser profile (saved logins/cookies)")
            dpg.add_checkbox(label="Headless", tag="chat_headless",
                             callback=lambda s, a: self._update_meta(headless=a))
            dpg.bind_item_theme(dpg.add_button(label="User info", callback=self.edit_user_info), "btn_ghost")
            dpg.bind_item_theme(dpg.add_button(label="Folder", callback=self.pick_work_folder), "btn_ghost")
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Selected folder for the built-in file tools (list/read/write/copy/...)")
            st.font(dpg.add_text("", tag="chat_folder", color=st.FAINT), "small")
        dpg.add_child_window(tag="chat_view", height=-130, border=False)
        dpg.bind_item_theme(dpg.last_item(), "flat")
        with dpg.child_window(height=-1, border=True, no_scrollbar=True):
            dpg.bind_item_theme(dpg.last_item(), "stat")
            with dpg.group(horizontal=True):
                dpg.add_input_text(tag="chat_input", multiline=True, width=-128, height=68, on_enter=True,
                                   callback=lambda: self.send())
                b = dpg.add_button(label="Send", width=112, height=68, callback=lambda: self.send())
                dpg.bind_item_theme(b, "btn_primary")
                st.font(b, "semibold")
            st.font(dpg.add_text("Enter to send  |  Ctrl+Enter for a new line  |  follow-ups reuse the saved plan",
                                 color=st.FAINT), "small")

    def _build_json_tab(self, key: str, filename: str, editable: bool) -> None:
        with dpg.group(horizontal=True):
            dpg.bind_item_theme(dpg.add_button(label="Reload", user_data=key,
                                               callback=lambda s, a, u: self._load_json(u, force=True)), "btn_secondary")
            if editable:
                dpg.bind_item_theme(dpg.add_button(label="Save edits", user_data=key,
                                                   callback=lambda s, a, u: self._save_json(u)), "btn_primary")
            st.font(dpg.add_text(filename, tag=f"{key}_path", color=st.FAINT), "small")
        w = dpg.add_input_text(tag=f"{key}_text", multiline=True, width=-1, height=-1,
                               readonly=not editable, tab_input=True, user_data=key,
                               callback=lambda s, a, u: self.json_dirty.__setitem__(u, True))
        st.font(w, "mono")

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        dpg.create_context()
        dpg.configure_app(manual_callback_management=True)
        st.load_fonts()
        st.setup_themes()
        self._build()
        dpg.create_viewport(title="Ecogent", width=1440, height=920, min_width=1100, min_height=680,
                            clear_color=st.BG)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window("main", True)
        sys.stdout = _StdoutToLog(self.events, sys.__stdout__)
        self.refresh_chats()
        llm = self.settings.main_llm
        if PROVIDERS.get(llm.provider, {}).get("needs_key") and not llm.api_key:
            self.log("Set your LLM provider (OpenAI, OpenRouter, Ollama or any OpenAI-compatible API) "
                     "in Settings before the first task.")
        try:
            while dpg.is_dearpygui_running():
                dpg.run_callbacks(dpg.get_callback_queue())
                self._poll()
                dpg.render_dearpygui_frame()
                dialogs.show_pending()
                self._after_frame()
        finally:
            self.scheduler.stop()
            self.worker.shutdown()
            self.worker.join(timeout=8)
            sys.stdout = sys.__stdout__
            dpg.destroy_context()

    def _after_frame(self) -> None:
        # Header: subtitle next to the title, controls pinned to the right edge.
        hw = dpg.get_item_rect_size("header_bar")[0]
        rw = dpg.get_item_rect_size("header_right")[0]
        if hw and rw:
            dpg.set_item_pos("header_right", [max(440, hw - rw - 20), 16])
            dpg.set_item_pos("header_sub", [166, 27])
        # Scroll max is only known after the new items were laid out.
        if self._scroll_chat:
            self._scroll_chat -= 1
            if not self._scroll_chat:
                dpg.set_y_scroll("chat_view", dpg.get_y_scroll_max("chat_view"))
        if self._scroll_log:
            self._scroll_log -= 1
            if not self._scroll_log:
                dpg.set_y_scroll("log_view", dpg.get_y_scroll_max("log_view"))

    # ------------------------------------------------------------------ helpers
    def log(self, text: str) -> None:
        for line in text.splitlines() or [""]:
            low = line.lower()
            color = st.DANGER if ("failed" in low or "error" in low) else \
                st.SUCCESS if ("run done" in low or "output written" in low or "browser ready" in low) else \
                st.WARNING if ("captcha" in low or "healing" in low or "waiting" in low) else st.MUTED
            st.font(dpg.add_text(line, parent="log_view", color=color), "small")
        children = dpg.get_item_children("log_view", 1) or []
        for item in children[: max(0, len(children) - MAX_LOG_LINES)]:
            dpg.delete_item(item)
        self._scroll_log = 2

    def set_status(self, text: str, kind: str = "ok") -> None:
        dpg.configure_item("status", label=f"  {text[:60]}  ")
        dpg.bind_item_theme("status", {"ok": "pill_ok", "busy": "pill_busy", "err": "pill_err"}.get(kind, "pill_info"))

    def session(self, chat_id: Optional[str] = None) -> Optional[ChatSession]:
        cid = chat_id or self.current
        return open_session(self.settings, cid) if cid else None

    def _update_meta(self, **kw) -> None:
        s = self.session()
        if s:
            s.update_meta(**kw)

    def _profiles(self) -> list[str]:
        p = self.settings.profile_path
        return sorted(d.name for d in p.iterdir() if d.is_dir()) if p.exists() else []

    def _profile_changed(self, sender, value) -> None:
        self._update_meta(profile="" if value.startswith("(") else value)

    # ------------------------------------------------------------------ chats
    def refresh_chats(self) -> None:
        dpg.delete_item("chat_list", children_only=True)
        query = (dpg.get_value("task_search") or "").strip().lower()
        chats = [m for m in ChatSession.list_all(self.settings.chats_path)
                 if not query or query in m.get("title", "").lower()]
        if not chats:
            st.font(dpg.add_text("No tasks yet.\nClick '+ New task' to start." if not query else "No matching tasks.",
                                 parent="chat_list", color=st.FAINT), "small")
        for m in chats:
            title = m.get("title", m["id"])
            title = title if len(title) <= 30 else title[:29] + "..."
            label = f"{title}\n{TASK_LABELS.get(m.get('task_type'), '')}   ·   {m.get('status', 'new')}"
            b = dpg.add_button(label=label, parent="chat_list", width=-1, height=70, user_data=m["id"],
                               callback=self._chat_clicked)
            dpg.bind_item_theme(b, "task_item_active" if m["id"] == self.current else "task_item")

    def _highlight_current(self) -> None:
        for item in dpg.get_item_children("chat_list", 1) or []:
            if dpg.get_item_type(item).endswith("mvButton"):
                dpg.bind_item_theme(item, "task_item_active" if dpg.get_item_user_data(item) == self.current else "task_item")

    def _chat_clicked(self, sender, value, chat_id) -> None:
        if chat_id != self.current:
            self.load_chat(chat_id)

    def load_chat(self, chat_id: str) -> None:
        self.current = chat_id
        s = self.session()
        if not s:
            return
        meta = s.meta
        dpg.configure_item("chat_type", label=f"  {TASK_LABELS.get(meta.get('task_type'), '-')}  ")
        dpg.configure_item("chat_profile", items=["(temporary profile)"] + self._profiles())
        dpg.set_value("chat_profile", meta.get("profile") or "(temporary profile)")
        dpg.set_value("chat_headless", bool(meta.get("headless")))
        dpg.set_value("chat_folder", meta.get("work_folder") or "no folder selected (output folder)")
        dpg.delete_item("chat_view", children_only=True)
        for m in s.chat.get("messages", []):
            self._append_chat(m["role"], m["text"])
        for key, filename, *_ in JSON_TABS:
            self.json_path[key] = s.folder / filename
            self._load_json(key, force=True)
        self._load_files()
        self._update_usage()
        self._highlight_current()

    def _append_chat(self, role: str, text: str) -> None:
        user = role == "user"
        indent = BUBBLE_INDENT if user else 0
        st.font(dpg.add_text("You" if user else "Ecogent", parent="chat_view", indent=indent + 4,
                             color=st.PRIMARY_HOVER if user else st.SUCCESS), "label")
        bubble = dpg.add_child_window(parent="chat_view", indent=indent, width=-1 if user else -BUBBLE_INDENT,
                                      auto_resize_y=True, border=True, no_scrollbar=True)
        dpg.bind_item_theme(bubble, "bubble_user" if user else "bubble_agent")
        dpg.add_text(text.strip(), parent=bubble, wrap=0)
        dpg.add_spacer(height=4, parent="chat_view")
        self._scroll_chat = 3

    def _load_json(self, key: str, force: bool = False) -> None:
        if self.json_dirty[key] and not force:
            return
        path = self.json_path.get(key)
        text = json.dumps(read_json(path, None), indent=2, ensure_ascii=False) if path and path.exists() else ""
        dpg.set_value(f"{key}_text", text)
        dpg.set_value(f"{key}_path", str(path) if path else "")
        self.json_dirty[key] = False

    def _save_json(self, key: str) -> None:
        path = self.json_path.get(key)
        if not path:
            return
        try:
            data = json.loads(dpg.get_value(f"{key}_text"))
        except json.JSONDecodeError as e:
            self.log(f"Not saved - invalid JSON in {path.name}: {e}")
            return
        write_json(path, data)
        self.json_dirty[key] = False
        self.log(f"{path.name} saved by you; the next run uses it.")

    def _update_usage(self) -> None:
        s = self.session()
        if not s:
            for tag in ("usage_in", "usage_out", "usage_calls", "usage_hits"):
                dpg.set_value(tag, "-")
            return
        u, runs = s.usage, s.plan.get("runs", [])
        hits = runs[-1].get("stats", {}).get("cache_hits", 0) if runs else 0
        dpg.set_value("usage_in", f"{u.get('input_tokens', 0):,}")
        dpg.set_value("usage_out", f"{u.get('output_tokens', 0):,}")
        dpg.set_value("usage_calls", f"{u.get('calls', 0)}")
        dpg.set_value("usage_hits", f"{hits}")

    def _load_files(self, *_) -> None:
        dpg.delete_item("files_list", children_only=True)
        s = self.session()
        if not s:
            return
        rows = []
        for kind, folder in (("output", s.output_dir), ("temp", s.temp_dir), ("chat", s.folder)):
            if folder.exists():
                rows += [(kind, p) for p in sorted(folder.rglob("*")) if p.is_file() and not p.name.endswith(".tmp")]
        if not rows:
            st.font(dpg.add_text("No files yet.", parent="files_list", color=st.FAINT), "small")
            return
        with dpg.table(parent="files_list", header_row=True, row_background=True, borders_innerH=True,
                       policy=dpg.mvTable_SizingStretchProp, scrollY=True, height=-1):
            dpg.add_table_column(label="Name", init_width_or_weight=3)
            dpg.add_table_column(label="Where", init_width_or_weight=0.8)
            dpg.add_table_column(label="Size", init_width_or_weight=0.8)
            dpg.add_table_column(label="", init_width_or_weight=0.6)
            for kind, p in rows:
                with dpg.table_row():
                    dpg.add_text(p.name)
                    with dpg.tooltip(dpg.last_item()):
                        dpg.add_text(str(p))
                    st.font(dpg.add_text(kind, color=st.MUTED), "small")
                    st.font(dpg.add_text(_human_size(p.stat().st_size), color=st.MUTED), "small")
                    b = dpg.add_button(label="Open", user_data=str(p), callback=lambda s_, a, u: open_path(Path(u)))
                    dpg.bind_item_theme(b, "btn_secondary")

    # ------------------------------------------------------------------ actions
    def new_task(self, prompt: str = "") -> None:
        dialogs.NewTaskDialog(self.settings, self._profiles(), prompt, self._create_task)

    def _create_task(self, r: dict) -> None:
        if r["task_type"] == "auto":
            self.worker.submit("Detect task type", self._auto_create, r)
            return
        s = self.worker.agent.new_chat(r["task_type"], r["title"], r["profile"], r["headless"])
        self.current = s.id
        self.refresh_chats()
        self.load_chat(s.id)
        if r["prompt"]:
            self._send_text(r["prompt"])

    def _auto_create(self, r: dict) -> None:
        """Worker thread: classify the prompt, then the user confirms the task type with the intent."""
        agent = self.worker.agent
        guess = agent.classify(r["prompt"])
        labels = [TASK_LABELS[t] for t in TASK_TYPES]
        choice = self.ui.choose("", f"Detected task type: {TASK_LABELS[guess['task_type']]}\n"
                                    f"Intent: {guess.get('intent', '')}\n\nConfirm or change the type:",
                                labels, TASK_LABELS[guess["task_type"]])
        if not choice:
            return
        s = agent.new_chat(TASK_TYPES[labels.index(choice)], r["title"], r["profile"], r["headless"])
        s.update_meta(intent=guess.get("intent", ""))
        self.ui.emit("select", s.id, prompt=r["prompt"])
        agent.handle_message(s.id, r["prompt"])

    def send(self) -> None:
        text = dpg.get_value("chat_input").strip()
        dpg.set_value("chat_input", "")
        if not text:
            return
        if not self.current:
            self.new_task(prompt=text)
            return
        self._send_text(text)

    def _send_text(self, text: str) -> None:
        self._append_chat("user", text)
        self.worker.submit("Task message", self.worker.agent.handle_message, self.current, text)

    def run_again(self) -> None:
        if self.current:
            self.worker.submit("Run again", self.worker.agent.rerun, self.current)

    def stop(self) -> None:
        self.worker.cancel()
        for d in self.request_dialogs:
            d.close()
        self.request_dialogs.clear()
        self.set_status("Stopping...", "err")

    def delete_chat(self) -> None:
        s = self.session()
        if not s:
            return

        def do(yes: bool) -> None:
            if not yes:
                return
            cid = self.current
            self.scheduler.remove(cid)
            self.current = None
            dpg.delete_item("chat_view", children_only=True)
            dpg.configure_item("chat_type", label="No task selected")
            self._update_usage()
            self.worker.submit("Delete task", self.worker.agent.delete_chat, cid)
        dialogs.ConfirmDialog(f"Delete '{s.meta.get('title')}' and its collected data?\n"
                              "(Files in the output folder are kept.)", do)

    def open_output(self) -> None:
        s = self.session()
        open_path(s.output_dir if s else self.settings.output_path)

    def edit_user_info(self) -> None:
        s = self.session()
        if not s:
            return

        def save(r: dict) -> None:
            s.save_user_info(r["info"])
            s.update_meta(user_info_file=r["file"])
            self._load_files()
        dialogs.UserInfoEditor(read_json(s.user_info_path, {}), s.meta.get("user_info_file", ""), save)

    def pick_work_folder(self) -> None:
        s = self.session()
        if not s:
            return

        def chosen(path: str) -> None:
            s.update_meta(work_folder=path)
            dpg.set_value("chat_folder", path)
            self.log(f"Selected folder for file tools: {path}")
        dialogs.pick_path(chosen, folder=True)

    def open_profiles(self) -> None:
        def setup(name: str, url: str) -> None:
            self.log(f"Opening browser for profile '{name}'. Log in, then close the browser window.")
            self.worker.submit("Profile setup", self.worker.agent.browser.setup_profile, name, url)
        dialogs.ProfilesDialog(self.settings.profile_path, setup)

    def open_schedules(self) -> None:
        s = self.session()
        cur = (s.id, s.meta.get("title", s.id)) if s else None
        dialogs.SchedulesDialog(self.scheduler, cur,
                                lambda cid: self.worker.submit("Run now", self.worker.agent.rerun, cid))

    def open_settings(self) -> None:
        def save(new: Settings) -> None:
            new.save()
            self.settings = new
            self.worker.submit("Apply settings", self.worker.agent.reload, new)
            self.log("Settings saved.")
            self.refresh_chats()
        dialogs.SettingsDialog(self.settings, save)

    def _schedule_from_agent(self, chat_id: str, sched: dict) -> None:
        s = open_session(self.settings, chat_id)
        self.scheduler.add(chat_id, s.meta.get("title", chat_id) if s else chat_id,
                           every_minutes=sched.get("every_minutes"), daily_at=sched.get("daily_at") or "")

    def _scheduled_due(self, chat_id: str) -> None:
        self.ui.log(f"Scheduled run due: {chat_id}")
        self.worker.submit("Scheduled run", self.worker.agent.rerun, chat_id, True)

    # ------------------------------------------------------------------ events from the worker
    def _poll(self) -> None:
        for _ in range(200):
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                return
            self._handle(ev)

    def _handle(self, ev: UIEvent) -> None:
        k, p, cid = ev.kind, ev.payload, ev.chat_id
        if k == "log":
            self.log(p.get("text", ""))
        elif k == "message":
            if cid == self.current:
                self._append_chat(p["role"], p["text"])
        elif k in ("files", "usage"):
            if cid == self.current:
                if k == "files":
                    for key, *_ in JSON_TABS:
                        self._load_json(key)
                self._update_usage()
        elif k == "chats":
            self.refresh_chats()
            if cid and cid == self.current:
                s = self.session()
                if s:
                    dpg.set_value("chat_profile", s.meta.get("profile") or "(temporary profile)")
        elif k == "select":
            self.current = cid
            self.refresh_chats()
            self.load_chat(cid)
            if p.get("prompt"):
                self._append_chat("user", p["prompt"])
        elif k == "status":
            self.set_status(p.get("text", ""), "busy" if self.worker.busy else "ok")
        elif k == "busy":
            busy = bool(p.get("busy"))
            dpg.configure_item("spinner", show=busy)
            dpg.configure_item("stop_btn", enabled=busy)
            self.set_status(p.get("label", "Working...") if busy else "Ready", "busy" if busy else "ok")
            if not busy and self.current:
                self._load_files()
                for key, *_ in JSON_TABS:
                    self._load_json(key)
                self._update_usage()
        elif k == "error":
            self.set_status("Error - see activity log", "err")
        elif k == "request":
            self._request(ev)

    def _request(self, ev: UIEvent) -> None:
        p = ev.payload
        req_id, kind = p["req_id"], p["req_kind"]

        def respond(value) -> None:
            self.ui.respond(req_id, value)
            self.request_dialogs[:] = [d for d in self.request_dialogs if dpg.does_item_exist(d.tag)]

        if ev.chat_id and ev.chat_id != self.current and open_session(self.settings, ev.chat_id):
            self.current = ev.chat_id
            self.refresh_chats()
            self.load_chat(ev.chat_id)
        if kind == "hold":
            d = dialogs.HoldDialog(p.get("message", ""), respond)
        elif kind == "confirm":
            d = dialogs.ConfirmDialog(p.get("message", ""), respond)
        elif kind == "choose":
            d = dialogs.ChoiceDialog(p.get("message", ""), p.get("options", []), p.get("default", ""), respond)
        elif kind == "sample":
            d = dialogs.SampleDialog(p.get("rows", []), p.get("note", ""), respond)
        elif kind == "user_info":
            d = dialogs.UserInfoDialog(p.get("fields", []), p.get("message", ""), respond)
        else:
            respond(None)
            return
        self.request_dialogs.append(d)


def main() -> None:
    EcogentApp().run()


if __name__ == "__main__":
    main()
