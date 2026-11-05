"""
Ecogent desktop GUI (DearPyGui) - modern web-app layout.

Sidebar: brand, new task, search, task cards (status dot, type, age), navigation.
Top bar: task title, type pill, status pill, Run again / Stop, activity-panel toggle.
Main card: welcome screen with task ideas, or chat (avatars, bubbles, composer) plus
plan.json / current_task.json / steps.json / chat.json and files tabs.
Inspector (right): token usage tiles + timestamped activity log.
All agent work runs on the Worker thread; the render loop only reacts to UIEvents.
"""

from __future__ import annotations

import inspect
import json
import os
import queue
import subprocess
import sys
import traceback
from datetime import datetime
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
SIDEBAR_W = 280
INSPECTOR_W = 340
TOPBAR_H = 64
COMPOSER_H = 112
GAP = 12
WELCOME_CARD_W = 360


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


def _ago(iso: str) -> str:
    try:
        sec = (datetime.now() - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return ""
    if sec < 60:
        return "just now"
    for limit, div, unit in ((3600, 60, "m"), (86400, 3600, "h"), (7 * 86400, 86400, "d")):
        if sec < limit:
            return f"{int(sec // div)}{unit} ago"
    return datetime.fromisoformat(iso).strftime("%b %d")


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
        self._welcome_indent: tuple = ()
        self._welcome_cards: list[int] = []

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        with dpg.window(tag="main", no_scrollbar=True):
            with dpg.group(horizontal=True, horizontal_spacing=GAP):
                self._build_sidebar()
                with dpg.group():
                    self._build_topbar()
                    with dpg.group(horizontal=True, horizontal_spacing=GAP):
                        with dpg.child_window(tag="main_card", width=-(INSPECTOR_W + GAP), height=-1, border=True):
                            dpg.bind_item_theme(dpg.last_item(), "card")
                            with dpg.tab_bar():
                                with dpg.tab(label=" Chat "):
                                    self._build_chat()
                                for key, filename, label, editable in JSON_TABS:
                                    with dpg.tab(label=f" {label} "):
                                        self._build_json_tab(key, filename, editable)
                                with dpg.tab(label=" Files "):
                                    with dpg.group(horizontal=True):
                                        dpg.bind_item_theme(dpg.add_button(label="Refresh", callback=self._load_files), "btn_secondary")
                                        dpg.bind_item_theme(dpg.add_button(label="Open output folder", callback=self.open_output), "btn_ghost")
                                    dpg.add_child_window(tag="files_list", border=False)
                                    dpg.bind_item_theme(dpg.last_item(), "flat")
                        self._build_inspector()

    def _build_sidebar(self) -> None:
        with dpg.child_window(tag="sidebar_panel", width=SIDEBAR_W, height=-1, border=True, no_scrollbar=True):
            dpg.bind_item_theme(dpg.last_item(), "sidebar")
            with dpg.group(horizontal=True, horizontal_spacing=12):
                logo = dpg.add_button(label="E", width=40, height=40)
                dpg.bind_item_theme(logo, "btn_primary")
                st.font(logo, "h2")
                with dpg.group() as brand:
                    dpg.bind_item_theme(brand, "tight")
                    st.font(dpg.add_text("Ecogent"), "h2")
                    st.font(dpg.add_text("token-efficient browser agent", color=st.FAINT), "small")
            dpg.add_spacer(height=4)
            card, _ = st.rich_button(0, 42, "btn_primary", callback=lambda: self.new_task())
            st.put_icon(card, "add", 84, 13, color=(255, 255, 255), size="icon_sm")
            st.put_text(card, "New task", 108, 8, "semibold", color=(255, 255, 255))
            dpg.add_input_text(tag="task_search", hint="Search tasks", width=-1,
                               callback=lambda: self.refresh_chats())
            with dpg.group(horizontal=True):
                st.section_label("Tasks")
                st.font(dpg.add_text("", tag="task_count", color=st.FAINT), "label")
            dpg.add_child_window(tag="chat_list", height=-(4 * 44 + 18), border=False)
            dpg.bind_item_theme(dpg.last_item(), "list")
            dpg.add_separator()
            for ic, label, cb in (("contact", "Browser profiles", self.open_profiles),
                                  ("clock", "Schedules", self.open_schedules),
                                  ("folder", "Output folder", self.open_output),
                                  ("settings", "Settings", self.open_settings)):
                card, _ = st.rich_button(0, 38, "nav_item", callback=cb)
                st.put_icon(card, ic, 14, 11, color=st.FAINT, size="icon_sm")
                st.put_text(card, label, 44, 6, color=st.MUTED)

    def _build_topbar(self) -> None:
        with dpg.child_window(tag="topbar_panel", height=TOPBAR_H, border=True, no_scrollbar=True):
            dpg.bind_item_theme(dpg.last_item(), "topbar")
            with dpg.group(tag="top_left", horizontal=True, horizontal_spacing=12):
                st.font(dpg.add_text("Welcome", tag="top_title"), "h2")
                dpg.add_button(tag="chat_type", label="No task selected", show=False)
                dpg.bind_item_theme("chat_type", "pill_info")
            with dpg.group(tag="top_right", horizontal=True):
                dpg.add_loading_indicator(tag="spinner", style=1, radius=1.3, show=False,
                                          color=st.PRIMARY_HOVER, secondary_color=st.SURFACE_2)
                dpg.add_button(tag="status", label="  Ready  ")
                dpg.bind_item_theme("status", "pill_ok")
                dpg.add_spacer(width=4)
                dpg.bind_item_theme(dpg.add_button(tag="run_btn", label="Run again", callback=self.run_again,
                                                   enabled=False), "btn_secondary")
                with dpg.tooltip("run_btn"):
                    dpg.add_text("Replay the saved plan (cached selectors, ~0 LLM tokens)")
                dpg.bind_item_theme(dpg.add_button(tag="stop_btn", label="Stop", callback=self.stop, show=False),
                                    "btn_danger")
                st.icon_button("panel", "Show / hide the activity panel", self.toggle_inspector,
                               fallback="Activity")

    def _build_inspector(self) -> None:
        with dpg.child_window(tag="inspector", width=INSPECTOR_W, height=-1, border=True, no_scrollbar=True):
            dpg.bind_item_theme(dpg.last_item(), "card")
            st.section_label("Usage  ·  this task")
            tile_w = (INSPECTOR_W - 32 - 10) // 2
            with dpg.group(horizontal=True):
                self._stat("usage_in", "Tokens in", tile_w)
                self._stat("usage_out", "Tokens out", tile_w)
            with dpg.group(horizontal=True):
                self._stat("usage_calls", "LLM calls", tile_w)
                self._stat("usage_hits", "Cache hits", tile_w)
            dpg.add_spacer(height=2)
            dpg.add_separator()
            with dpg.group(horizontal=True):
                st.section_label("Activity")
                dpg.add_spacer(width=INSPECTOR_W - 32 - 112)
                st.icon_button("delete", "Clear the activity log", self.clear_log, height=28, width=30,
                               fallback="Clear")
            dpg.add_child_window(tag="log_view", height=-1, border=False)
            dpg.bind_item_theme(dpg.last_item(), "list")

    def _stat(self, tag: str, label: str, width: int) -> None:
        with dpg.child_window(width=width, height=76, border=True, no_scrollbar=True):
            dpg.bind_item_theme(dpg.last_item(), "tile")
            st.font(dpg.add_text(label, color=st.FAINT), "small")
            st.font(dpg.add_text("-", tag=tag), "stat")

    def _build_chat(self) -> None:
        with dpg.group(tag="chat_toolbar", horizontal=True, show=False):
            dpg.add_combo(["(temporary profile)"], tag="chat_profile", width=220,
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
            st.icon_button("delete", "Delete this task", self.delete_chat, theme="btn_ghost", fallback="Delete")
        self._build_welcome()
        dpg.add_child_window(tag="chat_view", height=-(COMPOSER_H + 10), border=False, show=False)
        dpg.bind_item_theme(dpg.last_item(), "flat_pad")
        with dpg.child_window(height=COMPOSER_H, border=True, no_scrollbar=True):
            dpg.bind_item_theme(dpg.last_item(), "composer")
            with dpg.group(horizontal=True):
                w = dpg.add_input_text(tag="chat_input", multiline=True, width=-64, height=60, on_enter=True,
                                       callback=lambda: self.send())
                dpg.bind_item_theme(w, "input_bare")
                st.icon_button("send", "Send (Enter)", lambda: self.send(), theme="btn_primary",
                               width=52, height=52, fallback="Send")
            st.font(dpg.add_text("Enter to send  ·  Ctrl+Enter for a new line  ·  "
                                 "follow-ups reuse the saved plan", color=st.FAINT), "small")

    def _build_welcome(self) -> None:
        with dpg.child_window(tag="welcome", height=-(COMPOSER_H + 10), border=False):
            dpg.bind_item_theme(dpg.last_item(), "flat")
            dpg.add_spacer(height=36)
            with dpg.group(tag="welcome_inner"):
                st.font(dpg.add_text("What should Ecogent do?"), "h1")
                dpg.add_text("Describe a task in plain words. Ecogent plans it once, runs every step in Python\n"
                             "and caches what worked - so running it again costs almost no LLM tokens.",
                             color=st.FAINT)
                dpg.add_spacer(height=10)
                cards = [("list", "Scrape data", "Collect records from listings and pages,\nconfirm a sample, export CSV / JSON.", "scraping"),
                         ("chart", "Analyze pages", "Read pages or files and get a summary,\ncomparison or table.", "analysis"),
                         ("bolt", "Automate a flow", "Log in, fill forms and click through steps\nwith your saved browser profile.", "automation"),
                         ("chat", "Just describe it", "Write the prompt and let Ecogent\ndetect the task type for you.", "auto")]
                for i in range(0, len(cards), 2):
                    with dpg.group(horizontal=True, horizontal_spacing=12) as row:
                        for ic, title, desc, ttype in cards[i:i + 2]:
                            card, _ = st.rich_button(row, 104, "type_card", width=WELCOME_CARD_W, user_data=ttype,
                                                     callback=lambda s, a, u: self.new_task(task_type=u))
                            self._welcome_cards.append(card)
                            st.put_icon(card, ic, 20, 22, color=st.PRIMARY_HOVER, size="icon_lg")
                            st.put_text(card, title, 66, 14, "semibold")
                            st.put_text(card, desc, 66, 44, "small", color=st.FAINT)

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
                self._run_callbacks()
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

    def _run_callbacks(self) -> None:
        """Like dpg.run_callbacks, but one failing callback is logged instead of closing the app."""
        for job in dpg.get_callback_queue() or []:
            if job[0] is None:
                continue
            try:
                n = len(inspect.signature(job[0]).parameters)
                job[0](*job[1:n + 1])
            except Exception as e:  # noqa: BLE001 - keep the GUI alive, show the error
                self.log(f"Error: {type(e).__name__}: {e}")
                traceback.print_exc()

    def _after_frame(self) -> None:
        # Top bar: title vertically centred on the left, controls pinned to the right edge.
        tw = dpg.get_item_rect_size("topbar_panel")[0]
        lw, lh = dpg.get_item_rect_size("top_left")
        rw, rh = dpg.get_item_rect_size("top_right")
        if tw and rw:
            dpg.set_item_pos("top_left", [18, max(0, (TOPBAR_H - lh) // 2)])
            dpg.set_item_pos("top_right", [max(lw + 40, tw - rw - 16), max(0, (TOPBAR_H - rh) // 2)])
        # Welcome screen: size the idea cards to the space and centre them horizontally.
        if dpg.is_item_shown("welcome"):
            ww = dpg.get_item_rect_size("welcome")[0]
            card_w = max(260, min(WELCOME_CARD_W, (ww - 12) // 2))
            indent = max(0, (ww - (2 * card_w + 12)) // 2)
            if ww and (indent, card_w) != self._welcome_indent:
                self._welcome_indent = (indent, card_w)
                dpg.configure_item("welcome_inner", indent=indent)
                for card in self._welcome_cards:
                    dpg.configure_item(card, width=card_w)
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
        stamp = datetime.now().strftime("%H:%M:%S")
        for line in text.splitlines() or [""]:
            # BrowserManager prints emoji the UI font cannot draw; drop them instead of showing "?" boxes.
            line = "".join(ch for ch in line if ord(ch) < 0x2600 or 0x2800 <= ord(ch) < 0xFE00).strip()
            low = line.lower()
            color = st.DANGER if ("failed" in low or "error" in low) else \
                st.SUCCESS if ("run done" in low or "output written" in low or "browser ready" in low) else \
                st.WARNING if ("captcha" in low or "healing" in low or "waiting" in low) else st.MUTED
            with dpg.group(horizontal=True, parent="log_view", horizontal_spacing=8):
                st.font(dpg.add_text(stamp, color=(100, 116, 139)), "small")
                st.font(dpg.add_text(line, color=color, wrap=0), "small")
        children = dpg.get_item_children("log_view", 1) or []
        for item in children[: max(0, len(children) - MAX_LOG_LINES)]:
            dpg.delete_item(item)
        self._scroll_log = 2

    def clear_log(self, *_) -> None:
        dpg.delete_item("log_view", children_only=True)

    def toggle_inspector(self, *_) -> None:
        show = not dpg.is_item_shown("inspector")
        dpg.configure_item("inspector", show=show)
        dpg.configure_item("main_card", width=-(INSPECTOR_W + GAP) if show else -1)

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
        all_chats = ChatSession.list_all(self.settings.chats_path)
        chats = [m for m in all_chats if not query or query in m.get("title", "").lower()]
        dpg.set_value("task_count", str(len(all_chats)) if all_chats else "")
        if not chats:
            dpg.add_spacer(height=8, parent="chat_list")
            st.font(dpg.add_text("No tasks yet.\nClick 'New task' or pick an idea\non the right to start."
                                 if not query else "No matching tasks.",
                                 parent="chat_list", color=st.FAINT, indent=6), "small")
        for m in chats:
            status = m.get("status", "new")
            card, _ = st.rich_button("chat_list", 60, "task_item_active" if m["id"] == self.current else "task_item",
                                     callback=self._chat_clicked, user_data=m["id"])
            st.put_dot(card, 13, 16, status, callback=self._chat_clicked, user_data=m["id"])
            st.put_text(card, st.truncate(m.get("title") or m["id"], 25), 30, 6, "semibold")
            meta = "  ·  ".join(x for x in (TASK_LABELS.get(m.get("task_type"), ""), status,
                                                  _ago(m.get("updated", ""))) if x)
            st.put_text(card, meta, 30, 32, "small", color=st.FAINT)

    def _highlight_current(self) -> None:
        for card in dpg.get_item_children("chat_list", 1) or []:
            items = dpg.get_item_children(card, 1) or []
            # The first child of a task card is its full-size button (see st.rich_button).
            if items and dpg.get_item_type(items[0]).endswith("mvButton"):
                dpg.bind_item_theme(items[0], "task_item_active" if dpg.get_item_user_data(items[0]) == self.current
                                    else "task_item")

    def _chat_clicked(self, sender, value, chat_id) -> None:
        if chat_id != self.current:
            self.load_chat(chat_id)

    def _show_task_view(self, has_task: bool) -> None:
        dpg.configure_item("welcome", show=not has_task)
        dpg.configure_item("chat_view", show=has_task)
        dpg.configure_item("chat_toolbar", show=has_task)
        dpg.configure_item("chat_type", show=has_task)
        dpg.configure_item("run_btn", enabled=has_task)
        if not has_task:
            dpg.set_value("top_title", "Welcome")
            self._welcome_indent = ()

    def load_chat(self, chat_id: str) -> None:
        self.current = chat_id
        s = self.session()
        if not s:
            return
        meta = s.meta
        self._show_task_view(True)
        dpg.set_value("top_title", st.truncate(meta.get("title") or chat_id, 60))
        dpg.configure_item("chat_type", label=f"  {TASK_LABELS.get(meta.get('task_type'), '-')}  ")
        dpg.configure_item("chat_profile", items=["(temporary profile)"] + self._profiles())
        dpg.set_value("chat_profile", meta.get("profile") or "(temporary profile)")
        dpg.set_value("chat_headless", bool(meta.get("headless")))
        dpg.set_value("chat_folder", meta.get("work_folder") or "no folder selected (output folder)")
        dpg.delete_item("chat_view", children_only=True)
        for m in s.chat.get("messages", []):
            self._append_chat(m["role"], m["text"], m.get("time", ""))
        for key, filename, *_ in JSON_TABS:
            self.json_path[key] = s.folder / filename
            self._load_json(key, force=True)
        self._load_files()
        self._update_usage()
        self._highlight_current()

    def _append_chat(self, role: str, text: str, when: str = "") -> None:
        user = role == "user"
        try:
            stamp = datetime.fromisoformat(when).strftime("%H:%M") if when else datetime.now().strftime("%H:%M")
        except ValueError:
            stamp = ""
        with dpg.group(horizontal=True, parent="chat_view", horizontal_spacing=12):
            glyph = st.icon("user") if user else ""
            av = dpg.add_button(label=glyph or ("Y" if user else "E"), width=36, height=36)
            dpg.bind_item_theme(av, "avatar_user" if user else "avatar_agent")
            st.font(av, "icon" if glyph else "semibold")
            with dpg.group():
                with dpg.group(horizontal=True, horizontal_spacing=8):
                    st.font(dpg.add_text("You" if user else "Ecogent"), "semibold")
                    st.font(dpg.add_text(stamp, color=st.FAINT), "small")
                bubble = dpg.add_child_window(width=-48, auto_resize_y=True, border=True, no_scrollbar=True)
                dpg.bind_item_theme(bubble, "bubble_user" if user else "bubble_agent")
                dpg.add_text(text.strip(), parent=bubble, wrap=0)
        dpg.add_spacer(height=6, parent="chat_view")
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
    def new_task(self, prompt: str = "", task_type: str = "") -> None:
        dialogs.NewTaskDialog(self.settings, self._profiles(), prompt, self._create_task, task_type=task_type)

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
            self._show_task_view(False)
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
                    dpg.set_value("top_title", st.truncate(s.meta.get("title") or cid, 60))
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
            dpg.configure_item("stop_btn", show=busy)
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
