"""DearPyGui dialogs for Ecogent. All dialogs are non-blocking and answer through callbacks."""

from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional

import dearpygui.dearpygui as dpg

from ..config import LLM_PURPOSES, PROVIDERS, TASK_LABELS, TASK_TYPES, LLMConfig, Settings
from ..llm import LLMClient
from . import style as st
from .style import DANGER, SUCCESS
from ..scheduler import describe

from .style import SUBTLE as MUTED, WARNING as WARN

SYSTEM_LANG = "(system default)"
LANGUAGES = ("en-US", "en-GB", "bn-BD", "hi-IN", "de-DE", "fr-FR", "es-ES", "ar-SA", "zh-CN", "ja-JP", SYSTEM_LANG)


def _pos(w: int, h: int) -> list[int]:
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    return [max(0, (vw - w) // 2), max(0, (vh - h) // 3)]


def pick_path(callback: Callable[[str], None], folder: bool = False) -> None:
    """Open a DearPyGui file/folder picker; callback(path) on OK."""
    def done(sender, app_data):
        path = (app_data or {}).get("file_path_name", "")
        dpg.delete_item(sender)
        if path:
            callback(path)

    def cancel(sender, app_data):
        dpg.delete_item(sender)

    with dpg.file_dialog(directory_selector=folder, show=True, modal=True, width=760, height=440,
                         callback=done, cancel_callback=cancel):
        if not folder:
            dpg.add_file_extension(".*")
            dpg.add_file_extension(".json", color=(120, 220, 120))
            dpg.add_file_extension(".txt", color=(120, 180, 255))


_PENDING: list[list] = []


def show_pending() -> None:
    """Call once per frame after rendering."""
    for entry in list(_PENDING):
        entry[1] -= 1
        if entry[1] <= 0:
            _PENDING.remove(entry)
            if dpg.does_item_exist(entry[0]):
                dpg.configure_item(entry[0], show=True)
                dpg.focus_item(entry[0])


class Dialog:
    def __init__(self, title: str, width: int = 560, height: int = 380, modal: bool = True,
                 on_cancel: Optional[Callable[[], None]] = None):
        self.on_cancel = on_cancel
        self.tag = dpg.generate_uuid()
        # Created hidden and shown a few frames later (see show_pending): ImGui cannot open a
        # modal in the same frame another modal closed, so back-to-back dialogs would vanish.
        dpg.add_window(label=title, tag=self.tag, modal=modal, width=width, height=height, show=False,
                       pos=_pos(width, height), no_collapse=True, on_close=self._closed)
        dpg.bind_item_theme(self.tag, "dialog")
        _PENDING.append([self.tag, 2])

    def _closed(self, *_):
        cb, self.on_cancel = self.on_cancel, None
        self.close()
        if cb:
            cb()

    def close(self) -> None:
        self.on_cancel = None
        if dpg.does_item_exist(self.tag):
            dpg.delete_item(self.tag)

    def cancel(self, *_):
        self._closed()

    def row_buttons(self, ok_label: str, ok_cb, cancel_label: str = "Cancel") -> None:
        dpg.add_spacer(height=2, parent=self.tag)
        dpg.add_separator(parent=self.tag)
        dpg.add_spacer(height=2, parent=self.tag)
        with dpg.group(horizontal=True, parent=self.tag):
            dpg.bind_item_theme(dpg.add_button(label=ok_label, callback=ok_cb, width=170), "btn_primary")
            if cancel_label:
                dpg.bind_item_theme(dpg.add_button(label=cancel_label, callback=self.cancel, width=110), "btn_secondary")


# =========================================================================== new task
class NewTaskDialog(Dialog):
    TYPE_INFO = {
        "analysis": ("chart", "Read pages or files, summarize"),
        "scraping": ("list", "Collect records, export a table"),
        "automation": ("bolt", "Log in, fill forms, click flows"),
        "software_test": ("test", "Coming soon"),
        "others": ("doc", "Anything else in a browser"),
        "auto": ("spark", "Detect it from the prompt"),
    }
    CARD_W, CARD_H = 252, 78
    TEMP, NEW = "(temporary profile)", "+ New profile..."

    def __init__(self, settings: Settings, profiles: list[str], prompt: str, on_create: Callable[[dict], None],
                 task_type: str = "", on_open_browser: Optional[Callable[[str, str, str], None]] = None):
        super().__init__("New task", 830, 760)
        self.on_create = on_create
        self.on_open_browser = on_open_browser
        self.opened: set[str] = set()
        types = TASK_TYPES + ["auto"]
        self.ttype = task_type if task_type in types else ("auto" if prompt else TASK_TYPES[0])
        self.cards: dict[str, int] = {}
        p = self.tag
        dpg.add_text("Pick what Ecogent should do. The plan is made once and reused on every rerun.",
                     color=MUTED, parent=p)
        st.section_label("Task type", parent=p)
        for i in range(0, len(types), 3):
            with dpg.group(horizontal=True, horizontal_spacing=12, parent=p) as row:
                for t in types[i:i + 3]:
                    ic, desc = self.TYPE_INFO.get(t, ("doc", ""))
                    card, btn = st.rich_button(row, self.CARD_H, "type_card", width=self.CARD_W,
                                               callback=self._pick, user_data=t)
                    st.put_icon(card, ic, 16, 16, color=st.PRIMARY_HOVER, size="icon")
                    st.put_text(card, "Auto-detect" if t == "auto" else TASK_LABELS[t], 48, 10, "semibold")
                    st.put_text(card, desc, 48, 40, "small", color=MUTED)
                    self.cards[t] = btn
        self._pick(None, None, self.ttype)
        dpg.add_spacer(height=2, parent=p)
        st.section_label("Title (optional)", parent=p)
        self.title_w = dpg.add_input_text(width=-1, hint="e.g. Baby products under $50", parent=p)

        langs = list(LANGUAGES)
        cur = settings.browser_language or SYSTEM_LANG
        hdr = dpg.add_collapsing_header(label="Browser  -  profile, language, waits, login",
                                        default_open=False, parent=p)
        default = settings.default_profile if settings.default_profile in profiles else self.TEMP
        # One aligned grid: label | control | label | control | extra.
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, borders_innerH=False,
                       borders_outerH=False, borders_innerV=False, borders_outerV=False,
                       pad_outerX=False, parent=hdr):
            for _ in range(5):
                dpg.add_table_column()
            with dpg.table_row():
                self._grid_label("Profile", "Saved browser profile: keeps cookies and logins between runs,\n"
                                            "so sites see the same browser every time (far fewer captchas).")
                self.profile_w = dpg.add_combo(profiles + [self.TEMP, self.NEW], default_value=default,
                                               width=220, callback=self._profile_pick)
                self._grid_label("Language", "Browser language (Accept-Language header).")
                self.lang_w = dpg.add_combo(langs if cur in langs else [cur] + langs, default_value=cur, width=130)
                self.headless_w = dpg.add_checkbox(label="Headless", default_value=settings.headless)
            with dpg.table_row():
                self._grid_label("Page wait", "Extra pause after every page opens, for slow sites or\n"
                                              "pages that load their content late. 0 = no pause.")
                with dpg.group(horizontal=True, horizontal_spacing=6):
                    self.page_wait_w = dpg.add_input_int(default_value=settings.page_wait_s, width=70, step=0,
                                                         min_value=0, max_value=120, min_clamped=True,
                                                         max_clamped=True)
                    dpg.add_text("sec", color=MUTED)
                self._grid_label("Bot-check", "When a page shows a verification screen ('Just a moment...',\n"
                                              "'Checking your browser'), wait this long for it to pass by\n"
                                              "itself before asking you to solve it. 0 = ask right away.")
                with dpg.group(horizontal=True, horizontal_spacing=6):
                    self.bot_wait_w = dpg.add_input_int(default_value=settings.bot_check_wait_s, width=70, step=0,
                                                        min_value=0, max_value=300, min_clamped=True,
                                                        max_clamped=True)
                    dpg.add_text("sec", color=MUTED)
                dpg.add_text("")
        self.new_name_w = dpg.add_input_text(width=220, hint="new profile name", show=False, parent=hdr)
        dpg.add_separator(parent=hdr)
        st.font(dpg.add_text("Log in or solve a captcha ahead of time (optional)", color=MUTED, parent=hdr), "small")
        with dpg.group(horizontal=True, horizontal_spacing=10, parent=hdr):
            self.url_w = dpg.add_input_text(width=-150, hint="Site URL, e.g. https://scholar.google.com")
            self.open_btn = b = dpg.add_button(label="Open browser", width=-1, callback=self._open_browser)
            dpg.bind_item_theme(b, "btn_secondary")
            with dpg.tooltip(b):
                dpg.add_text("Opens the selected profile at this URL. Log in / solve the captcha,\n"
                             "then CLOSE the window: the session is saved and reused on every run.")
        # Right under the button (the user looks here while the browser is open); hidden when empty.
        self.browser_msg_w = dpg.add_text("", color=WARN, wrap=740, show=False, parent=hdr)
        dpg.add_spacer(height=2, parent=hdr)
        st.section_label("Task prompt (optional - you can also type it in the chat)", parent=p)
        self.prompt_w = dpg.add_input_text(multiline=True, default_value=prompt, width=-1, height=120, parent=p)
        self.msg_w = dpg.add_text("", color=WARN, parent=p)
        self.row_buttons("Create task", self.ok)

    @staticmethod
    def _grid_label(text: str, tip: str) -> None:
        w = dpg.add_text(text, color=MUTED)
        with dpg.tooltip(w):
            dpg.add_text(tip)

    def _browser_status(self, text: str, color=WARN) -> None:
        dpg.configure_item(self.browser_msg_w, color=color, show=bool(text))
        dpg.set_value(self.browser_msg_w, text)

    def _pick(self, sender, app_data, ttype):
        self.ttype = ttype
        for t, btn in self.cards.items():
            dpg.bind_item_theme(btn, "type_card_active" if t == ttype else "type_card")

    def _profile_pick(self, sender, value):
        dpg.configure_item(self.new_name_w, show=value == self.NEW)

    def _lang(self) -> str:
        lang = dpg.get_value(self.lang_w)
        return "" if lang == SYSTEM_LANG else lang

    def _profile_name(self) -> Optional[str]:
        """Selected profile ("" = temporary), or None (message shown) when a new one has no name."""
        profile = dpg.get_value(self.profile_w)
        if profile == self.NEW:
            profile = re.sub(r"[^\w.-]+", "_", dpg.get_value(self.new_name_w).strip()).strip("_.")
            if not profile:
                dpg.set_value(self.msg_w, "Enter a name for the new browser profile.")
                return None
        return "" if profile == self.TEMP else profile

    def _open_browser(self, *_):
        profile = self._profile_name()
        if profile is None:
            return
        if not profile:
            self._browser_status(color=WARN, text="Pick or create a profile first - a temporary profile is not kept.")
            return
        if not self.on_open_browser:
            return
        self.on_open_browser(profile, dpg.get_value(self.url_w).strip(), self._lang())
        self.opened.add(profile)
        if dpg.get_value(self.profile_w) == self.NEW:
            items = dpg.get_item_configuration(self.profile_w)["items"]
            if profile not in items:
                dpg.configure_item(self.profile_w, items=items[:-1] + [profile, self.NEW])
            dpg.set_value(self.profile_w, profile)
            self._profile_pick(None, profile)
        dpg.configure_item(self.open_btn, label="Browser is open...", enabled=False)
        self._browser_status(color=WARN, text=f"Browser opening for '{profile}'. Log in / solve the captcha there, then CLOSE "
                                  "that browser window. This message changes when the session is saved.")

    def profile_done(self, profile: str, error: str = "") -> None:
        """The profile setup job ended (called by the app when the user closed the browser)."""
        if not dpg.does_item_exist(self.tag):
            return
        dpg.configure_item(self.open_btn, label="Open browser", enabled=True)
        if error:
            self._browser_status(color=DANGER, text=f"Could not open the browser for '{profile}': {error[:200]}")
            return
        self._browser_status(color=SUCCESS, text=f"Browser closed - session saved in profile '{profile}'. "
                                  "You can create the task now.")

    def ok(self, *_):
        prompt = dpg.get_value(self.prompt_w).strip()
        ttype = self.ttype
        if ttype == "auto" and not prompt:
            dpg.set_value(self.msg_w, "Write the task prompt so Ecogent can detect the type.")
            return
        is_new = dpg.get_value(self.profile_w) == self.NEW
        profile = self._profile_name()
        if profile is None:
            return
        # A new profile that was not opened yet is set up before the task (queued first on the worker).
        new_profile_url = (dpg.get_value(self.url_w).strip() or "about:blank") \
            if is_new and profile not in self.opened else ""
        result = {"task_type": ttype, "title": dpg.get_value(self.title_w).strip(),
                  "profile": profile, "new_profile_url": new_profile_url,
                  "browser_lang": self._lang(),
                  "page_wait": dpg.get_value(self.page_wait_w), "bot_wait": dpg.get_value(self.bot_wait_w),
                  "headless": dpg.get_value(self.headless_w), "prompt": prompt}
        self.close()
        self.on_create(result)


# =========================================================================== settings
class SettingsDialog(Dialog):
    def __init__(self, settings: Settings, on_save: Callable[[Settings], None]):
        super().__init__("Settings", 900, 830)
        self.settings, self.on_save = settings, on_save
        self.w: dict[str, int] = {}
        with dpg.tab_bar(parent=self.tag) as self.tabs:
            with dpg.tab(label="General"):
                self._path("home", "Home folder (chats, memory)", settings.home, True)
                self._path("temp_dir", "Temp folder  (default <home>/temp)", settings.temp_dir, True)
                self._path("output_dir", "Output folder  (default <home>/output)", settings.output_dir, True)
                self._path("profile_dir", "Browser profiles  (default <home>/profiles)", settings.profile_dir, True)
                self._path("browser_path", "Browser executable  (empty = auto-detect)", settings.browser_path, False)
                self.w["browser_language"] = dpg.add_input_text(
                    label="Browser language (e.g. en-US; empty = system / IP default)",
                    default_value=settings.browser_language, width=160)
                self.w["debug_port"] = dpg.add_input_int(label="Debug port", default_value=settings.debug_port, width=160)
                self.w["page_timeout_ms"] = dpg.add_input_int(label="Page timeout (ms)", default_value=settings.page_timeout_ms, width=160)
                self.w["page_wait_s"] = dpg.add_input_int(label="Page wait after each load (s, new tasks)",
                                                          default_value=settings.page_wait_s, width=160)
                self.w["bot_check_wait_s"] = dpg.add_input_int(label="Bot-check wait before asking you (s, new tasks)",
                                                               default_value=settings.bot_check_wait_s, width=160)
                self.w["headless"] = dpg.add_checkbox(label="Headless mode by default (otherwise graphics mode)", default_value=settings.headless)
            with dpg.tab(label="Main LLM") as self.main_tab:
                dpg.add_text("The strong model: planning, healing and the final analysis.", color=MUTED)
                self.main = self._llm(settings.main_llm, ["openai", "openrouter", "compatible", "anthropic"])
            with dpg.tab(label="Cheap model"):
                dpg.add_text("Optional second model for low-level jobs (e.g. gpt-4o-mini, a flash / haiku model).",
                             color=MUTED)
                self.cheap = self._llm(settings.cheap_llm, ["none", "openai", "openrouter", "anthropic", "compatible"])
                dpg.add_text("Jobs sent to the cheap model (the rest use the main model):")
                self.purposes = {}
                with dpg.group(horizontal=True):
                    for p in LLM_PURPOSES:
                        self.purposes[p] = dpg.add_checkbox(label=p, default_value=p in settings.cheap_purposes)
            with dpg.tab(label="Advanced"):
                for key, label in (("max_heal_attempts", "Max heal attempts per step"),
                                   ("scrape_sample_size", "Scraping sample size"),
                                   ("max_page_chars", "Max chars per page sent to LLM"),
                                   ("analysis_direct_chars", "Analyze in one call up to (chars)"),
                                   ("analysis_budget_chars", "Relevance filter: page text for analysis (chars, 0 = off)"),
                                   ("max_heals_per_run", "Max LLM heals per run"),
                                   ("max_rescue_turns", "ReAct fallback: moves per failed step (0 = off)"),
                                   ("max_rescues_per_run", "ReAct fallback: steps per run"),
                                   ("max_run_tokens", "Token budget per run (0 = unlimited)")):
                    self.w[key] = dpg.add_input_int(label=label, default_value=getattr(settings, key), width=160)
                self.w["use_vector_memory"] = dpg.add_checkbox(label="Use ChromaDB vector memory to reuse similar plans",
                                                               default_value=settings.use_vector_memory)
        self.err = dpg.add_text("", color=WARN, parent=self.tag)
        self.row_buttons("Save", self.ok)

    def _path(self, key, label, value, folder):
        dpg.add_text(label, color=MUTED)
        with dpg.group(horizontal=True):
            w = dpg.add_input_text(default_value=value, width=640)
            dpg.add_button(label="Browse", callback=lambda: pick_path(lambda p: dpg.set_value(w, p), folder))
        self.w[key] = w

    PROVIDER_HINTS = {
        "openai": "OpenAI API - needs an API key (platform.openai.com).",
        "openrouter": "OpenRouter - one key for many models, e.g. 'openai/gpt-4o-mini', 'meta-llama/llama-3.1-70b-instruct'.",
        "compatible": "Any OpenAI-compatible API, e.g. Groq https://api.groq.com/openai/v1, "
                      "Together https://api.together.xyz/v1, DeepSeek https://api.deepseek.com/v1",
        "anthropic": "Anthropic Messages API - needs an API key.",
        "none": "Disabled - every job uses the main LLM.",
    }

    def _llm(self, cfg: LLMConfig, keys: list[str]):
        labels = {k: ("Disabled" if k == "none" else PROVIDERS[k]["label"]) for k in keys}
        current = cfg.provider if cfg.provider in keys else keys[0]
        w = {"_labels": labels}
        hint = None

        def on_provider(sender, label):
            key = next(k for k, v in labels.items() if v == label)
            url = dpg.get_value(w["base_url"]).strip()
            preset_urls = {p["base_url"] for p in PROVIDERS.values()}
            if key in PROVIDERS and (not url or url in preset_urls):
                dpg.set_value(w["base_url"], PROVIDERS[key]["base_url"])
            dpg.set_value(hint, self.PROVIDER_HINTS.get(key, ""))

        w["provider"] = dpg.add_combo(list(labels.values()), default_value=labels[current], label="Provider",
                                      width=260, callback=on_provider)
        hint = dpg.add_text(self.PROVIDER_HINTS.get(current, ""), color=MUTED)
        w["base_url"] = dpg.add_input_text(label="Base URL", default_value=cfg.base_url, width=520)
        w["api_key"] = dpg.add_input_text(label="API key", default_value=cfg.api_key, password=True, width=520)
        with dpg.group(horizontal=True):
            w["model"] = dpg.add_input_text(label="Model", default_value=cfg.model, width=300)
            models = dpg.add_combo([], width=200, no_preview=False, default_value="pick from list",
                                   callback=lambda s, a: dpg.set_value(w["model"], a))
        with dpg.group(horizontal=True):
            test_btn = dpg.add_button(label="Test connection / fetch models")
            dpg.bind_item_theme(test_btn, "btn_secondary")
            status = dpg.add_text("", color=MUTED)

        def test():
            dpg.set_value(status, "Connecting...")
            try:
                found = LLMClient(self._llm_from(w)).list_models()
                dpg.configure_item(models, items=found)
                dpg.set_value(status, f"Connected - {len(found)} models available")
                dpg.configure_item(status, color=SUCCESS)
            except Exception as e:  # network errors are shown to the user, not raised
                dpg.set_value(status, f"Failed: {str(e)[:110]}")
                dpg.configure_item(status, color=DANGER)
        dpg.set_item_callback(test_btn, lambda: threading.Thread(target=test, daemon=True).start())
        w["_test"], w["_status"], w["_models"] = test, status, models

        w["max_tokens"] = dpg.add_input_int(label="Max output tokens", default_value=cfg.max_tokens, width=160)
        w["temperature"] = dpg.add_input_float(label="Temperature", default_value=cfg.temperature, width=160, step=0.1)
        w["timeout"] = dpg.add_input_int(label="Timeout (s)", default_value=cfg.timeout, width=160)
        return w

    @staticmethod
    def _llm_from(w) -> LLMConfig:
        label = dpg.get_value(w["provider"])
        provider = next((k for k, v in w["_labels"].items() if v == label), "none")
        return LLMConfig(provider=provider, base_url=dpg.get_value(w["base_url"]).strip(),
                         api_key=dpg.get_value(w["api_key"]).strip(), model=dpg.get_value(w["model"]).strip(),
                         max_tokens=int(dpg.get_value(w["max_tokens"])),
                         temperature=float(dpg.get_value(w["temperature"])), timeout=int(dpg.get_value(w["timeout"])))

    def ok(self, *_):
        data = asdict(self.settings)
        for key in ("home", "temp_dir", "output_dir", "profile_dir", "browser_path", "browser_language"):
            data[key] = dpg.get_value(self.w[key]).strip()
        for key in ("debug_port", "page_timeout_ms", "page_wait_s", "bot_check_wait_s", "max_heal_attempts", "scrape_sample_size",
                    "max_page_chars", "analysis_direct_chars", "analysis_budget_chars", "max_heals_per_run",
                    "max_rescue_turns", "max_rescues_per_run", "max_run_tokens", "headless", "use_vector_memory"):
            data[key] = dpg.get_value(self.w[key])
        if not data["home"]:
            dpg.set_value(self.err, "Home folder is required.")
            return
        s = Settings._from_dict(data)
        s.main_llm = self._llm_from(self.main)
        s.cheap_llm = self._llm_from(self.cheap)
        s.cheap_purposes = [p for p, w in self.purposes.items() if dpg.get_value(w)]
        self.close()
        self.on_save(s)


# =========================================================================== agent requests
class HoldDialog(Dialog):
    """Not modal: the user works in the browser window and then presses Continue."""

    def __init__(self, message: str, on_answer: Callable[[bool], None]):
        super().__init__("Ecogent needs you", 560, 290, modal=False, on_cancel=lambda: on_answer(False))
        self.on_answer = on_answer
        dpg.add_text("Waiting for you", color=WARN, parent=self.tag)
        dpg.add_text(message, wrap=490, parent=self.tag)
        self.row_buttons("Continue", self.ok, "Abort run")

    def ok(self, *_):
        self.close()
        self.on_answer(True)


class ConfirmDialog(Dialog):
    def __init__(self, message: str, on_answer: Callable[[bool], None]):
        super().__init__("Ecogent", 600, 320, on_cancel=lambda: on_answer(False))
        self.on_answer = on_answer
        dpg.add_text(message, wrap=530, parent=self.tag)
        self.row_buttons("Yes", self.ok, "No")

    def ok(self, *_):
        self.close()
        self.on_answer(True)


class ChoiceDialog(Dialog):
    def __init__(self, message: str, options: list[str], default: str, on_answer: Callable[[Optional[str]], None]):
        super().__init__("Ecogent", 560, 330, on_cancel=lambda: on_answer(None))
        self.on_answer = on_answer
        dpg.add_text(message, wrap=490, parent=self.tag)
        self.combo = dpg.add_combo(options, default_value=default or (options[0] if options else ""), width=300, parent=self.tag)
        self.row_buttons("Confirm", self.ok)

    def ok(self, *_):
        v = dpg.get_value(self.combo)
        self.close()
        self.on_answer(v)


class SampleDialog(Dialog):
    def __init__(self, rows: list[dict], note: str, on_answer: Callable[[dict], None]):
        super().__init__("Confirm sample data", 1040, 700, on_cancel=lambda: on_answer({"ok": False, "comment": "cancelled"}))
        self.on_answer = on_answer
        cols: list[str] = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        dpg.add_text(note or "Check the sample records.", wrap=940, parent=self.tag)
        with dpg.table(parent=self.tag, header_row=True, resizable=True, scrollY=True, scrollX=True, height=330,
                       borders_innerH=True, borders_outerH=True, borders_innerV=True, borders_outerV=True,
                       policy=dpg.mvTable_SizingFixedFit):
            for c in cols:
                dpg.add_table_column(label=c, width_fixed=True, init_width_or_weight=200)
            for r in rows:
                with dpg.table_row():
                    for c in cols:
                        dpg.add_text(str(r.get(c, ""))[:160], wrap=190)
        dpg.add_text("If something is wrong, describe it (e.g. 'price is empty', 'title includes rating'):", parent=self.tag)
        self.comment = dpg.add_input_text(multiline=True, width=-1, height=60, parent=self.tag)
        with dpg.group(horizontal=True, parent=self.tag):
            dpg.bind_item_theme(dpg.add_button(label="Looks correct - scrape all", callback=self.ok, width=240), "btn_primary")
            dpg.bind_item_theme(dpg.add_button(label="Reject - heal the pattern", callback=self.reject, width=240), "btn_danger")

    def ok(self, *_):
        self.close()
        self.on_answer({"ok": True, "comment": ""})

    def reject(self, *_):
        comment = dpg.get_value(self.comment).strip()
        self.close()
        self.on_answer({"ok": False, "comment": comment})


class UserInfoDialog(Dialog):
    def __init__(self, fields: list[str], message: str, on_answer: Callable[[Optional[dict]], None]):
        super().__init__("Information for the task", 680, 190 + 46 * max(1, len(fields)) + 70,
                         on_cancel=lambda: on_answer(None))
        self.on_answer = on_answer
        if message:
            dpg.add_text(message, wrap=600, parent=self.tag)
        self.w = {}
        for f in fields:
            with dpg.group(horizontal=True, parent=self.tag):
                w = dpg.add_input_text(label=f, width=420)
                dpg.add_button(label="File...", callback=lambda s, a, u: pick_path(lambda p: dpg.set_value(u, p)), user_data=w)
            self.w[f] = w
        self.row_buttons("Save", self.ok)

    def ok(self, *_):
        result = {k: dpg.get_value(w).strip() for k, w in self.w.items()}
        self.close()
        self.on_answer(result)


class UserInfoEditor(Dialog):
    """Edit user_info.json of a chat and attach an external info file."""

    def __init__(self, info: dict, attached: str, on_save: Callable[[dict], None]):
        super().__init__("User info for this chat", 720, 560)
        self.on_save = on_save
        dpg.add_text("JSON object used for {{user.<field>}} values (stored in this chat folder):", parent=self.tag)
        self.text = dpg.add_input_text(multiline=True, default_value=json.dumps(info, indent=2, ensure_ascii=False),
                                       width=-1, height=300, tab_input=True, parent=self.tag)
        with dpg.group(horizontal=True, parent=self.tag):
            self.file = dpg.add_input_text(label="Info file (json/txt)", default_value=attached, width=420)
            dpg.add_button(label="Browse", callback=lambda: pick_path(lambda p: dpg.set_value(self.file, p)))
        self.err = dpg.add_text("", color=WARN, parent=self.tag)
        self.row_buttons("Save", self.ok)

    def ok(self, *_):
        try:
            info = json.loads(dpg.get_value(self.text).strip() or "{}")
            if not isinstance(info, dict):
                raise ValueError("must be a JSON object")
        except ValueError as e:
            dpg.set_value(self.err, f"Invalid JSON: {e}")
            return
        result = {"info": info, "file": dpg.get_value(self.file).strip()}
        self.close()
        self.on_save(result)


# =========================================================================== profiles
class ProfilesDialog(Dialog):
    def __init__(self, profile_root: Path, on_setup: Callable[[str, str], None]):
        super().__init__("Browser profiles", 640, 560, modal=False)
        self.root_dir, self.on_setup = profile_root, on_setup
        dpg.add_text("A profile keeps cookies and logins. 'Open browser to log in' opens a real browser window: "
                     "log in, solve any captcha, then CLOSE the window to save the session.",
                     color=MUTED, wrap=570, parent=self.tag)
        self.list = dpg.add_listbox([], num_items=7, width=-1, parent=self.tag)
        self.name = dpg.add_input_text(label="Profile name", width=360, parent=self.tag)
        self.url = dpg.add_input_text(label="Destination URL", hint="https://example.com/login  (opened in the browser)",
                                      width=360, parent=self.tag)
        self.msg = dpg.add_text("", color=WARN, parent=self.tag)
        with dpg.group(horizontal=True, parent=self.tag):
            dpg.bind_item_theme(dpg.add_button(label="Open browser to log in", callback=self.setup), "btn_primary")
            dpg.add_button(label="Delete selected", callback=self.delete)
            dpg.add_button(label="Refresh", callback=self.refresh)
            dpg.add_button(label="Close", callback=self.cancel)
        self.refresh()

    def names(self) -> list[str]:
        return sorted(p.name for p in self.root_dir.iterdir() if p.is_dir()) if self.root_dir.exists() else []

    def refresh(self, *_):
        if dpg.does_item_exist(self.list):
            dpg.configure_item(self.list, items=self.names())

    def setup(self, *_):
        name = dpg.get_value(self.name).strip() or dpg.get_value(self.list) or ""
        if not name:
            dpg.set_value(self.msg, "Enter a profile name (or select one to update).")
            return
        url = dpg.get_value(self.url).strip()
        self.on_setup(name, "" if url in ("", "https://") else url)
        dpg.set_value(self.msg, f"Browser opening for '{name}'. Close it when you are done.")

    def delete(self, *_):
        name = dpg.get_value(self.list)
        if not name:
            return
        ConfirmDialog(f"Delete profile '{name}' and its saved logins?",
                      lambda yes: (shutil.rmtree(self.root_dir / name, ignore_errors=True), self.refresh()) if yes else None)


# =========================================================================== schedules
class SchedulesDialog(Dialog):
    def __init__(self, scheduler, current_chat: Optional[tuple[str, str]], on_run_now: Callable[[str], None]):
        super().__init__("Schedules", 920, 500, modal=False)
        self.scheduler, self.current_chat, self.on_run_now = scheduler, current_chat, on_run_now
        self.table_parent = dpg.add_group(parent=self.tag)
        dpg.add_separator(parent=self.tag)
        target = f"current chat: {current_chat[1]}" if current_chat else "select a chat first"
        dpg.add_text(f"Add schedule for {target}", color=MUTED, parent=self.tag)
        with dpg.group(horizontal=True, parent=self.tag):
            self.rule = dpg.add_input_text(label="minutes (e.g. 60) or daily HH:MM", width=160)
            dpg.bind_item_theme(dpg.add_button(label="Add", callback=self.add), "btn_primary")
            dpg.add_button(label="Close", callback=self.cancel)
        self.msg = dpg.add_text("", color=WARN, parent=self.tag)
        self.refresh()

    def refresh(self, *_):
        if not dpg.does_item_exist(self.table_parent):
            return
        dpg.delete_item(self.table_parent, children_only=True)
        with dpg.table(parent=self.table_parent, header_row=True, height=250, scrollY=True,
                       policy=dpg.mvTable_SizingStretchProp, borders_innerH=True):
            for c in ("Title", "Rule", "Enabled", "Next run", "Last run", ""):
                dpg.add_table_column(label=c)
            for e in self.scheduler.entries():
                with dpg.table_row():
                    dpg.add_text(e.get("title", ""))
                    dpg.add_text(describe(e))
                    dpg.add_text("yes" if e.get("enabled", True) else "no")
                    dpg.add_text(e.get("next_run") or "")
                    dpg.add_text(e.get("last_run") or "")
                    with dpg.group(horizontal=True):
                        cid = e["chat_id"]
                        dpg.add_button(label="On/Off", user_data=cid, callback=lambda s, a, u: (self.scheduler.toggle(u), self.refresh()))
                        dpg.add_button(label="Run", user_data=cid, callback=lambda s, a, u: self.on_run_now(u))
                        dpg.add_button(label="X", user_data=cid, callback=lambda s, a, u: (self.scheduler.remove(u), self.refresh()))

    def add(self, *_):
        if not self.current_chat:
            dpg.set_value(self.msg, "Select a chat first.")
            return
        rule = dpg.get_value(self.rule).strip()
        try:
            if ":" in rule:
                self.scheduler.add(self.current_chat[0], self.current_chat[1], daily_at=rule)
            elif rule.isdigit():
                self.scheduler.add(self.current_chat[0], self.current_chat[1], every_minutes=int(rule))
            else:
                raise ValueError("use a number of minutes or HH:MM")
        except ValueError as e:
            dpg.set_value(self.msg, f"Invalid schedule: {e}")
            return
        dpg.set_value(self.msg, "")
        self.refresh()
