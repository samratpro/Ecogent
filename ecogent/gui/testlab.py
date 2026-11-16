"""
Test Lab window (sidebar -> Test Lab): the neutral test shop on port 3010.

  1. Shop        status, Start / Stop, open it in the browser
  2. Scenarios   one-click site versions with a plain explanation (base, code change, redesign, new data, ...)
  3. Advanced    each setting on its own (code, layout, wording, popups, data)
  4. Checks      free look / flow checks, with their last result, and a log

The app owns the shop server and the check process (closing the window stops neither).
"""

from __future__ import annotations

import webbrowser
from datetime import datetime
from typing import Callable

import dearpygui.dearpygui as dpg

from .. import test_shop as ts
from . import style as st
from .dialogs import Dialog
from .style import DANGER, SUCCESS, SUBTLE as MUTED, WARNING as WARN

BASE = {"markup": 0, "layout": 0, "copy": 0, "interruptions": 0, "content": 0}
# (title, what a visitor / agent would notice, settings) - each one a real-world kind of website change.
SCENARIOS = [
    ("Original shop", "The starting point. Run every task here first.", {}),
    ("Rebuilt code", "Developers rebuilt the site: class names and test ids change. Looks exactly the same.", {"markup": 1}),
    ("Refactored code", "Extra wrappers, buttons become divs, code order changes. Looks exactly the same.", {"markup": 2}),
    ("New code every visit", "Class names change on every page load, like some modern builds. Looks the same.", {"markup": 3}),
    ("Moved navigation", "Categories move into a Menu drawer, filters into a top bar, 'Load more' instead of pages.", {"layout": 1}),
    ("Full redesign", "New listing grid, filter dialog, colour swatches, one-page checkout.", {"layout": 2}),
    ("New wording", "Labels rewritten: 'Add to bag', 'Check out', 'Log in', 'Promo code' ...", {"copy": 1}),
    ("Popups", "Cookie banner plus a newsletter popup that blocks the page.", {"interruptions": 2}),
    ("New data", "Prices, stock and some products change. Layout stays the same. (Clears carts and orders.)", {"content": 1}),
    ("Everything changed", "Refactored code + redesign + new wording + popups + new data, all at once.",
     {"markup": 2, "layout": 2, "copy": 1, "interruptions": 2, "content": 1}),
]
TITLES = {"markup": "Code (same look)", "layout": "Layout", "copy": "Wording", "interruptions": "Popups"}
CHECK_HELP = {"Shop look check": "Proves code changes keep the exact same look (pixels and words).",
              "Shop flow check": "Proves a normal user can buy a product in every version."}


class LabControls:
    """What the window needs from the app."""

    def __init__(self, shop, run_check: Callable[[str], None], check_running: Callable[[], bool],
                 lines: Callable[[], list], last_results: Callable[[], dict]):
        self.shop, self.run_check, self.check_running = shop, run_check, check_running
        self.lines, self.last_results = lines, last_results


def describe(c: dict) -> str:
    parts = [f"{TITLES[k]}: {ts.AXES[k][c[k]]}" for k in TITLES]
    parts.append(f"Data: {'original' if not c['content'] else 'changed #' + str(c['content'])}")
    return "   ·   ".join(parts)


class TestLabDialog(Dialog):
    def __init__(self, ctl: LabControls):
        super().__init__("Test Lab", 1000, 800, modal=False)
        self.ctl = ctl
        self.config: dict | None = None
        self.scenario_btns: list[tuple[int, dict]] = []
        p = self.tag
        if not ts.available():
            dpg.add_text("The test_shop/ folder was not found next to the ecogent package.", color=WARN, parent=p)
            return
        st.font(dpg.add_text("A practice web shop for testing browser agents when a website changes. Every agent "
                             "sees the same version; agents never see these controls or the right answers.",
                             color=MUTED, wrap=940, parent=p), "small")
        # ---- 1. shop status
        with dpg.child_window(height=92, border=True, parent=p) as card:
            dpg.bind_item_theme(card, "tile")
            with dpg.group(horizontal=True, horizontal_spacing=14):
                with dpg.group():
                    self.state_text = dpg.add_text("")
                    st.font(self.state_text, "semibold")
                    self.version_text = dpg.add_text("", color=MUTED, wrap=600)
                    st.font(self.version_text, "small")
                dpg.add_spacer(width=10)
                self.toggle_btn = dpg.add_button(label="Start shop", width=130, height=40, callback=self._toggle)
                dpg.bind_item_theme(dpg.add_button(label="Open shop", height=40, callback=lambda: webbrowser.open(ts.PUBLIC_URL)),
                                    "btn_secondary")
                st.icon_button("refresh", "Refresh", self.refresh, fallback="Refresh")
        # ---- 2. scenarios
        dpg.add_spacer(height=4, parent=p)
        with dpg.group(horizontal=True, parent=p):
            st.section_label("1. Pick a scenario")
            st.font(dpg.add_text("one click changes the shop for everyone", color=MUTED), "small")
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchSame, parent=p):
            for _ in range(2):
                dpg.add_table_column()
            for i in range(0, len(SCENARIOS), 2):
                with dpg.table_row():
                    for title, desc, cfg in SCENARIOS[i:i + 2]:
                        with dpg.group():
                            b = dpg.add_button(label=title, width=-1, user_data=cfg, callback=lambda s, a, u: self._apply({**BASE, **u}))
                            dpg.bind_item_theme(b, "btn_secondary")
                            self.scenario_btns.append((b, {**BASE, **cfg}))
                            st.font(dpg.add_text(desc, color=MUTED, wrap=440), "small")
        self.msg = dpg.add_text("", color=WARN, parent=p)
        # ---- 3. advanced
        with dpg.collapsing_header(label="2. Advanced: set each part yourself", default_open=False, parent=p):
            self.combos: dict[str, int] = {}
            with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit):
                dpg.add_table_column()
                dpg.add_table_column()
                for k, labels in ts.AXES.items():
                    with dpg.table_row():
                        dpg.add_text(TITLES[k])
                        self.combos[k] = dpg.add_combo([f"{i} - {l}" for i, l in enumerate(labels)], default_value=f"0 - {labels[0]}", width=340)
                with dpg.table_row():
                    dpg.add_text("Data")
                    with dpg.group(horizontal=True):
                        self.content = dpg.add_input_int(default_value=0, min_value=0, max_value=999, min_clamped=True,
                                                         max_clamped=True, width=150)
                        st.font(dpg.add_text("0 = original; 1, 2, ... = different changed data", color=MUTED), "small")
            dpg.bind_item_theme(dpg.add_button(label="Apply these settings", callback=self._apply_advanced), "btn_primary")
        # ---- 4. checks + tools
        dpg.add_spacer(height=4, parent=p)
        st.section_label("3. Checks and tools", parent=p)
        with dpg.group(horizontal=True, parent=p):
            self.check_btns = []
            for label in ts.check_commands():
                b = dpg.add_button(label=f"Run {label.lower().replace('shop ', '')}", user_data=label, callback=lambda s, a, u: self._check(u))
                dpg.bind_item_theme(b, "btn_secondary")
                with dpg.tooltip(b):
                    dpg.add_text(CHECK_HELP[label] + " Free, about 1-2 minutes.")
                self.check_btns.append(b)
            dpg.add_spacer(width=12)
            dpg.bind_item_theme(dpg.add_button(label="Clear carts and orders", callback=self._reset), "btn_ghost")
            dpg.bind_item_theme(dpg.add_button(label="Lab page (browser)", callback=lambda: webbrowser.open(ts.lab_page_url())), "btn_ghost")
        self.results_text = dpg.add_text("", parent=p)
        st.font(self.results_text, "small")
        self.log = dpg.add_input_text(multiline=True, readonly=True, width=-1, height=-1, parent=p,
                                      default_value="\n".join(ctl.lines()))
        st.font(self.log, "mono")
        self.refresh()

    # ------------------------------------------------------------------ actions
    def _toggle(self, *_) -> None:
        if self.ctl.shop.running or self.ctl.shop.state == "running":
            self.ctl.shop.stop()
        else:
            self.ctl.shop.start()
        self.refresh()

    def _call(self, path: str, body: dict, done: str) -> None:
        try:
            r = ts.lab(path, body)
        except (OSError, ValueError) as e:
            dpg.set_value(self.msg, "The shop is not running - press Start shop first." if isinstance(e, OSError) else f"Refused: {e}")
            dpg.configure_item(self.msg, color=WARN)
            return
        dpg.set_value(self.msg, done + ("  Carts and orders were cleared (new data)." if r.get("reset") else ""))
        dpg.configure_item(self.msg, color=SUCCESS)
        self.refresh()

    def _apply(self, cfg: dict) -> None:
        name = next((t for t, _, c in SCENARIOS if {**BASE, **c} == cfg), "Custom version")
        self._call("/config", cfg, f"Applied: {name}.  Reload the shop page in the browser to see it.")

    def _apply_advanced(self, *_) -> None:
        cfg = {k: int(dpg.get_value(w).split(" ", 1)[0]) for k, w in self.combos.items()}
        cfg["content"] = dpg.get_value(self.content)
        self._apply(cfg)

    def _reset(self, *_) -> None:
        self._call("/reset", {}, "Carts, orders and the event log were cleared.")

    def _check(self, label: str) -> None:
        if self.config is None:
            dpg.set_value(self.msg, "Start the shop first - the checks need it running.")
            dpg.configure_item(self.msg, color=WARN)
            return
        self.ctl.run_check(label)
        self.refresh()

    # ------------------------------------------------------------------ view
    def append(self, line: str) -> None:
        if dpg.does_item_exist(self.tag) and hasattr(self, "log"):
            dpg.set_value(self.log, "\n".join(self.ctl.lines()))

    def refresh(self, *_) -> None:
        if not dpg.does_item_exist(self.tag) or not hasattr(self, "state_text"):
            return
        try:
            s = ts.lab("/state", timeout=1.5)
        except (OSError, ValueError):
            s = None
        self.config = s["config"] if s else None
        state = self.ctl.shop.state
        if s:
            c = s["config"]
            dpg.set_value(self.state_text, f"●  Running at {ts.PUBLIC_URL}")
            dpg.configure_item(self.state_text, color=SUCCESS)
            dpg.set_value(self.version_text, f"{describe(c)}\n{len(s['orders'])} orders, {len(s['events'])} actions recorded since the last clear")
            dpg.configure_item(self.toggle_btn, label="Stop shop")
            dpg.bind_item_theme(self.toggle_btn, "btn_danger")
            for k, labels in ts.AXES.items():
                dpg.set_value(self.combos[k], f"{c[k]} - {labels[c[k]]}")
            dpg.set_value(self.content, c["content"])
        else:
            text, color = {"starting": ("◌  Starting...  the first start installs and builds (about a minute)", WARN),
                           "running": ("◌  Starting...", WARN),
                           "failed": ("✕  Could not start - see the log below", DANGER)}.get(state, ("○  Stopped", MUTED))
            dpg.set_value(self.state_text, text)
            dpg.configure_item(self.state_text, color=color)
            dpg.set_value(self.version_text, "Press Start shop. It runs on your computer only (localhost:3010).")
            dpg.configure_item(self.toggle_btn, label="Start shop", enabled=state != "starting")
            dpg.bind_item_theme(self.toggle_btn, "btn_primary")
        cur = {k: self.config[k] for k in BASE} if self.config else None
        for b, cfg in self.scenario_btns:
            dpg.bind_item_theme(b, "btn_primary" if cur == cfg else "btn_secondary")
        busy = self.ctl.check_running()
        for b in self.check_btns:
            dpg.configure_item(b, enabled=not busy)
        res = self.ctl.last_results()
        parts = [f"{k}: {v}" for k, v in res.items()]
        dpg.set_value(self.results_text, ("Running a check...   " if busy else "") + ("   ·   ".join(parts) or "No check run yet."))
        dpg.configure_item(self.results_text, color=DANGER if any("FAIL" in v for v in res.values()) else
                           SUCCESS if res else MUTED)


def stamp() -> str:
    return datetime.now().strftime("%H:%M")
