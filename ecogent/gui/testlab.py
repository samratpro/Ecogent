"""
Test Lab window (sidebar -> Test Lab): the neutral test shop on port 3010.

  Server                   status, Start / Stop server, open in browser
  Scenarios                one-click site versions (baseline, markup, navigation, redesign, copy, interstitials, data)
  Custom configuration     each dimension set separately (markup, layout, copy, interstitials, data)
  Validation and tools     visual invariance and task-completion tests with their last result, and a log

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
    ("Baseline", "Unmodified site. Cold runs start here.", {}),
    ("Markup rebuild", "Class names and test IDs regenerated, as after a rebuild. Rendering unchanged.", {"markup": 1}),
    ("Markup refactor", "Wrapper elements, role-based buttons, reordered DOM. Rendering unchanged.", {"markup": 2}),
    ("Per-load markup", "Class names regenerated on every page load. Rendering unchanged.", {"markup": 3}),
    ("Navigation change", "Categories in a menu drawer, filters in a top bar, incremental loading.", {"layout": 1}),
    ("Redesign", "New listing grid, filter dialog, colour swatches, single-page checkout.", {"layout": 2}),
    ("Copy change", "Interface labels rewritten ('Add to bag', 'Check out', 'Log in', 'Promo code').", {"copy": 1}),
    ("Interstitials", "Cookie banner and a blocking newsletter modal.", {"interruptions": 2}),
    ("Data change", "Prices, stock and part of the catalogue change; layout unchanged. Clears session data.", {"content": 1}),
    ("Combined changes", "Markup refactor, redesign, copy change, interstitials and data change together.",
     {"markup": 2, "layout": 2, "copy": 1, "interruptions": 2, "content": 1}),
]
TITLES = {"markup": "Markup", "layout": "Layout", "copy": "Copy", "interruptions": "Interstitials"}
CHECK_HELP = {"Shop visual invariance test": "Verifies that markup changes leave rendering and visible text unchanged.",
              "Shop task-completion test": "Verifies that a scripted user can complete a purchase in every version."}


class LabControls:
    """What the window needs from the app."""

    def __init__(self, shop, run_check: Callable[[str], None], check_running: Callable[[], bool],
                 lines: Callable[[], list], last_results: Callable[[], dict]):
        self.shop, self.run_check, self.check_running = shop, run_check, check_running
        self.lines, self.last_results = lines, last_results


def describe(c: dict) -> str:
    parts = [f"{TITLES[k]}: {ts.AXES[k][c[k]]}" for k in TITLES]
    parts.append(f"Data: {'baseline' if not c['content'] else 'variant ' + str(c['content'])}")
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
        st.font(dpg.add_text("Controlled e-commerce environment for evaluating browser agents under website change. All clients "
                             "receive the same version; configuration and ground truth are not accessible to agents.",
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
                self.toggle_btn = dpg.add_button(label="Start server", width=130, height=40, callback=self._toggle)
                dpg.bind_item_theme(dpg.add_button(label="Open in browser", height=40, callback=lambda: webbrowser.open(ts.PUBLIC_URL)),
                                    "btn_secondary")
                st.icon_button("refresh", "Refresh", self.refresh, fallback="Refresh")
        # ---- 2. scenarios
        dpg.add_spacer(height=4, parent=p)
        with dpg.group(horizontal=True, parent=p):
            st.section_label("Scenarios")
            st.font(dpg.add_text("applied to all clients", color=MUTED), "small")
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
        with dpg.collapsing_header(label="Custom configuration", default_open=False, parent=p):
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
                        st.font(dpg.add_text("0 = baseline; 1, 2, ... = data variants", color=MUTED), "small")
            dpg.bind_item_theme(dpg.add_button(label="Apply", callback=self._apply_advanced), "btn_primary")
        # ---- 4. checks + tools
        dpg.add_spacer(height=4, parent=p)
        st.section_label("Validation and tools", parent=p)
        with dpg.group(horizontal=True, parent=p):
            self.check_btns = []
            for label in ts.check_commands():
                b = dpg.add_button(label=label.replace("Shop ", "").capitalize(), user_data=label, callback=lambda s, a, u: self._check(u))
                dpg.bind_item_theme(b, "btn_secondary")
                with dpg.tooltip(b):
                    dpg.add_text(CHECK_HELP[label] + " No API cost; about 1-2 minutes.")
                self.check_btns.append(b)
            dpg.add_spacer(width=12)
            dpg.bind_item_theme(dpg.add_button(label="Reset session data", callback=self._reset), "btn_ghost")
            dpg.bind_item_theme(dpg.add_button(label="Lab console", callback=lambda: webbrowser.open(ts.lab_page_url())), "btn_ghost")
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
            dpg.set_value(self.msg, "Server not running. Start the server first." if isinstance(e, OSError) else f"Request rejected: {e}")
            dpg.configure_item(self.msg, color=WARN)
            return
        dpg.set_value(self.msg, done + ("  Session data cleared (data change)." if r.get("reset") else ""))
        dpg.configure_item(self.msg, color=SUCCESS)
        self.refresh()

    def _apply(self, cfg: dict) -> None:
        name = next((t for t, _, c in SCENARIOS if {**BASE, **c} == cfg), "Custom configuration")
        self._call("/config", cfg, f"Applied: {name}. Reload open shop pages to see it.")

    def _apply_advanced(self, *_) -> None:
        cfg = {k: int(dpg.get_value(w).split(" ", 1)[0]) for k, w in self.combos.items()}
        cfg["content"] = dpg.get_value(self.content)
        self._apply(cfg)

    def _reset(self, *_) -> None:
        self._call("/reset", {}, "Session data and event log cleared.")

    def _check(self, label: str) -> None:
        if self.config is None:
            dpg.set_value(self.msg, "Start the server first; validation requires it.")
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
            dpg.set_value(self.version_text, f"{describe(c)}\n{len(s['orders'])} orders, {len(s['events'])} events since the last reset")
            dpg.configure_item(self.toggle_btn, label="Stop server")
            dpg.bind_item_theme(self.toggle_btn, "btn_danger")
            for k, labels in ts.AXES.items():
                dpg.set_value(self.combos[k], f"{c[k]} - {labels[c[k]]}")
            dpg.set_value(self.content, c["content"])
        else:
            text, color = {"starting": ("◌  Starting (first start installs dependencies and builds; about one minute)", WARN),
                           "running": ("◌  Starting...", WARN),
                           "failed": ("✕  Start failed; see the log below", DANGER)}.get(state, ("○  Stopped", MUTED))
            dpg.set_value(self.state_text, text)
            dpg.configure_item(self.state_text, color=color)
            dpg.set_value(self.version_text, "Local server on localhost:3010.")
            dpg.configure_item(self.toggle_btn, label="Start server", enabled=state != "starting")
            dpg.bind_item_theme(self.toggle_btn, "btn_primary")
        cur = {k: self.config[k] for k in BASE} if self.config else None
        for b, cfg in self.scenario_btns:
            dpg.bind_item_theme(b, "btn_primary" if cur == cfg else "btn_secondary")
        busy = self.ctl.check_running()
        for b in self.check_btns:
            dpg.configure_item(b, enabled=not busy)
        res = self.ctl.last_results()
        parts = [f"{k}: {v}" for k, v in res.items()]
        dpg.set_value(self.results_text, ("Validation running...   " if busy else "") + ("   ·   ".join(parts) or "No validation run yet."))
        dpg.configure_item(self.results_text, color=DANGER if any("FAIL" in v for v in res.values()) else
                           SUCCESS if res else MUTED)


def stamp() -> str:
    return datetime.now().strftime("%H:%M")
