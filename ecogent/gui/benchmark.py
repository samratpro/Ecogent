"""
Benchmark window: results of bench/drift_bench.py runs, what the automatic benchmark runs, and when.

Tabs
  Results    pick result CSVs (bench/results) -> per-system overview, pass rate / cost per drift level,
             the individual runs; buttons for the markdown summary (bench/summarize.py) and figures (bench/plot.py)
  Run        tasks, systems, drift levels, seeds, prices ... -> Run now / Stop, free checks, live output
  Schedule   off / once / daily / weekly; the app starts the run itself when it is due

The window only shows and starts things; the app (EcogentApp) owns the subprocess and the schedule,
so closing the window never stops a running benchmark.
"""

from __future__ import annotations

from typing import Callable

import dearpygui.dearpygui as dpg

import threading

from .. import bench_runner as br
from .. import paper_mode as pm
from ..config import ABLATIONS, Settings
from . import style as st
from .dialogs import ConfirmDialog, Dialog
from .style import DANGER, SUCCESS, SUBTLE as MUTED, WARNING as WARN

VARIANT_HELP = {
    "ecogent": "Ecogent, the full system",
    "nocache": "Ecogent with no reuse: every run is a new chat (no-reuse baseline)",
    "compile_only": "plan once, never repair on reruns (Agentic-Compilation-style baseline)",
    "no_cheap": "Ecogent with the cheap model off (main model for every job)",
    "stagehand": "external: Stagehand v3 cache + selfHeal (needs node + npm install)",
    "browser_use": "external: browser-use, LLM decides every step, screenshots on as shipped (needs .venv-baselines)",
    "browser_use_novision": "external: browser-use with screenshots off (text only, like Ecogent's page view)",
    **{k: f"ablation: {v}" for k, v in ABLATIONS.items()},
}


def _table_h(rows: int) -> int:
    """Height of a scrollable table showing all its rows (header + rows + room for the scrollbar)."""
    return 58 + 48 * max(1, rows)


class BenchmarkDialog(Dialog):
    def __init__(self, settings: Settings, ctl: "BenchControls"):
        super().__init__("Benchmark", 1080, 760, modal=False)
        self.settings, self.ctl = settings, ctl
        self.cfg = br.load_config(settings)
        self.file_boxes: dict[str, int] = {}
        if not br.available():
            dpg.add_text("The bench/ folder was not found next to the ecogent package, so the benchmark cannot "
                         "run from this installation. Run the app from the source folder.", color=WARN,
                         wrap=1000, parent=self.tag)
            return
        self.tabs: dict[str, int] = {}
        with dpg.tab_bar(parent=self.tag) as self.tab_bar:
            with dpg.tab(label=" Experiment ") as self.tabs["paper"]:
                self._build_paper()
            with dpg.tab(label=" Results ") as self.tabs["results"]:
                self._build_results()
            with dpg.tab(label=" Configuration ") as self.tabs["run"]:
                self._build_run()
            with dpg.tab(label=" Log ") as self.tabs["output"]:
                self._build_output()
            with dpg.tab(label=" Schedule ") as self.tabs["schedule"]:
                self._build_schedule()
        self.refresh_files()
        self.update_state()
        self.paper_check()

    # ------------------------------------------------------------------ paper run tab
    def _build_paper(self) -> None:
        st.font(dpg.add_text("Runs intended for publication must satisfy the reproducibility checklist. The checklist is stored "
                             "with the results (meta.json); unmet requirements are reported as deviations.",
                             color=MUTED, wrap=1000), "small")
        keys = list(pm.PRESETS)
        with dpg.group(horizontal=True):
            st.section_label("Experiment")
            self.paper_preset = dpg.add_combo([pm.PRESETS[k]["title"] for k in keys], default_value=pm.PRESETS[keys[0]]["title"],
                                              width=360, callback=self._paper_preset_changed)
        self.paper_about = dpg.add_text("", color=MUTED, wrap=1000)
        with dpg.group(horizontal=True, horizontal_spacing=18):
            self.paper_name = dpg.add_input_text(label="Result name", width=260, callback=self.paper_check)
            self.paper_date = dpg.add_input_text(label="Pricing date", hint="YYYY-MM-DD", width=120,
                                                 default_value=self.cfg.get("price_date", ""), callback=self.paper_check)
        self.paper_prices = dpg.add_text("", color=MUTED, wrap=1000)
        st.font(self.paper_prices, "small")
        dpg.add_spacer(height=2)
        with dpg.group(horizontal=True):
            st.section_label("Reproducibility checklist")
            dpg.add_button(label="Refresh", small=True, callback=self.paper_check)
        self.paper_table = dpg.add_group()
        self.paper_verdict = dpg.add_text("")
        st.font(self.paper_verdict, "semibold")
        with dpg.group(horizontal=True):
            self.paper_go = dpg.add_button(label="Run experiment", width=170, callback=lambda: self._paper_start(False))
            dpg.bind_item_theme(self.paper_go, "btn_primary")
            self.paper_force = dpg.add_button(label="Run with deviations", callback=lambda: self._paper_start(True))
            dpg.bind_item_theme(self.paper_force, "btn_ghost")
            dpg.add_spacer(width=16)
            dpg.bind_item_theme(dpg.add_button(label="Open pre-registration", callback=self._prereg), "btn_secondary")
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Creates bench/preregistration.md from a template (if missing) and opens it. "
                             "State the hypotheses, then commit the file before the run.")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            st.section_label("Report")
            self.report_combo = dpg.add_combo([], width=320)
            dpg.bind_item_theme(dpg.add_button(label="Generate report", callback=self._paper_report), "btn_secondary")
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("Protocol, deviations, statistics (mean ± sd, 95% CI, paired tests, cost of ownership) "
                             "and figures in one Markdown file")
        self.report_msg = dpg.add_text("", color=MUTED)
        self._paper_preset_changed()

    def _paper_key(self) -> str:
        title = dpg.get_value(self.paper_preset)
        return next(k for k, v in pm.PRESETS.items() if v["title"] == title)

    def _paper_preset_changed(self, *_) -> None:
        key = self._paper_key()
        p = pm.PRESETS[key]
        dpg.set_value(self.paper_about, p["about"] + ("" if p["paper"] else "  The checklist is informational for this experiment."))
        dpg.set_value(self.paper_name, pm.preset_config(key, self.cfg)["out_name"])
        self.paper_check()

    def _paper_cfg(self) -> tuple:
        key = self._paper_key()
        base = dict(self.read_form()) if hasattr(self, "run_btn") else dict(self.cfg)
        cfg = pm.preset_config(key, base)
        cfg["out_name"] = dpg.get_value(self.paper_name).strip() or cfg["out_name"]
        cfg["price_date"] = dpg.get_value(self.paper_date).strip()
        return key, cfg

    def paper_check(self, *_) -> None:
        if not dpg.does_item_exist(self.tag) or not hasattr(self, "paper_table") or not hasattr(self, "run_btn"):
            return
        key, cfg = self._paper_cfg()
        paper = pm.PRESETS[key]["paper"]
        checks = pm.readiness(self.settings, cfg, paper)
        dpg.set_value(self.paper_prices, f"Pricing (edit in Configuration): {cfg.get('prices') or 'none'}  ·  "
                      f"{br.count_runs(cfg)[1]} runs, site {cfg['site']}, seeds {cfg['seeds']}")
        dpg.delete_item(self.paper_table, children_only=True)
        with dpg.table(parent=self.paper_table, header_row=True, policy=dpg.mvTable_SizingStretchProp, borders_innerH=True,
                       row_background=True, scrollY=True, height=300):
            for col in ("Status", "Requirement", "Current state", "Action required"):
                dpg.add_table_column(label=col)
            for ch in checks:
                with dpg.table_row():
                    mark, col = ("Pass", SUCCESS) if ch.ok else (("Fail", DANGER) if ch.required else ("Warning", WARN))
                    dpg.add_text(mark, color=col)
                    dpg.add_text(ch.name + ("" if ch.required else " (recommended)"))
                    dpg.add_text(ch.detail, wrap=280)
                    dpg.add_text("" if ch.ok else ch.fix, wrap=380, color=MUTED)
        ok = pm.ready(checks)
        n_bad = sum(1 for c in checks if c.required and not c.ok)
        dpg.set_value(self.paper_verdict, "All requirements met." if ok and paper else
                      "Exploratory experiment: not marked as protocol compliant." if not paper else
                      f"{n_bad} requirement(s) not met. Resolve them, or run with deviations (they are recorded in the report).")
        dpg.configure_item(self.paper_verdict, color=SUCCESS if ok and paper else WARN if not paper else DANGER)
        running = self.ctl.running()
        dpg.configure_item(self.paper_go, enabled=(ok or not paper) and not running and not br.validate(cfg))
        dpg.configure_item(self.paper_force, show=paper and not ok, enabled=not running and not br.validate(cfg))
        files = [f.stem for f in br.result_files() if f.with_suffix(".manifest.json").exists()]
        dpg.configure_item(self.report_combo, items=files)
        if files and not dpg.get_value(self.report_combo):
            dpg.set_value(self.report_combo, files[0])

    def _paper_start(self, force: bool) -> None:
        key, cfg = self._paper_cfg()
        checks = pm.readiness(self.settings, cfg, pm.PRESETS[key]["paper"])
        errs = br.validate(cfg)
        if errs:
            dpg.set_value(self.paper_verdict, " ".join(errs))
            return
        cells, runs = br.count_runs(cfg)
        bad = [c.name for c in checks if c.required and not c.ok]
        msg = (f"Run '{pm.PRESETS[key]['title']}'?\n\n{runs} runs in {cells} cells -> {cfg['out_name']}.csv. "
               "This uses the paid API and may take several hours; a browser window opens for each cell.\n"
               + ("\nUnmet requirements (recorded as deviations):\n- " + "\n- ".join(bad) if bad else ""))

        def go(yes: bool) -> None:
            if not yes:
                return
            cfg["meta"] = str(pm.write_meta(self.settings, cfg, key, checks))
            self.cfg = {k: v for k, v in cfg.items() if k != "meta"}
            br.save_config(self.settings, dict(self.cfg))
            self.ctl.start(cfg, scheduled=False)
            if dpg.does_item_exist(self.tab_bar):
                dpg.set_value(self.tab_bar, self.tabs["output"])
            self.update_state()
        ConfirmDialog(msg, go)

    def _prereg(self, *_) -> None:
        path = pm.create_prereg()
        self.ctl.open_file(path)
        self.paper_check()

    def _paper_report(self, *_) -> None:
        name = dpg.get_value(self.report_combo)
        if not name:
            dpg.set_value(self.report_msg, "No result file available.")
            return
        dpg.set_value(self.report_msg, f"Generating report for {name}...")

        def job() -> None:
            try:
                out = pm.paper_report(br.RESULTS / f"{name}.csv")
                self.ctl.report_done(str(out), "")
            except Exception as e:  # noqa: BLE001 - shown to the user
                self.ctl.report_done("", f"{type(e).__name__}: {e}")
        threading.Thread(target=job, daemon=True, name="ecogent-paper-report").start()

    def report_finished(self, path: str, error: str) -> None:
        if dpg.does_item_exist(self.tag) and hasattr(self, "report_msg"):
            dpg.set_value(self.report_msg, f"Report saved: {path}" if path else f"Report generation failed: {error}")

    # ------------------------------------------------------------------ results tab
    def _build_results(self) -> None:
        with dpg.group(horizontal=True):
            dpg.bind_item_theme(dpg.add_button(label="Refresh", callback=self.refresh_files), "btn_secondary")
            dpg.bind_item_theme(dpg.add_button(label="Summary (Markdown)", callback=lambda: self.ctl.summary(self.checked())),
                                "btn_secondary")
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("bench/summarize.py: mean ± sd, 95% CI, paired tests, cost of ownership (Markdown)")
            dpg.bind_item_theme(dpg.add_button(label="Figures", callback=lambda: self.ctl.figures(self.checked())),
                                "btn_secondary")
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text("bench/plot.py: cost and success by level, cumulative cost, ablations, lookup steps (SVG)")
            dpg.bind_item_theme(dpg.add_button(label="Open results folder", callback=self.ctl.open_results), "btn_ghost")
        with dpg.group(horizontal=True):
            with dpg.child_window(width=270, height=-1, border=True):
                st.section_label("Result files")
                st.font(dpg.add_text("Select one or more files; their rows are combined.", color=MUTED, wrap=240), "small")
                self.files_parent = dpg.add_group()
            with dpg.child_window(width=-1, height=-1, border=True) as right:
                self.results_parent = right

    def checked(self) -> list:
        return [p for p in br.result_files() if dpg.does_item_exist(self.file_boxes.get(p.name, 0))
                and dpg.get_value(self.file_boxes[p.name])]

    def refresh_files(self, *_) -> None:
        if not dpg.does_item_exist(self.files_parent):
            return
        before = {n for n, b in self.file_boxes.items() if dpg.does_item_exist(b) and dpg.get_value(b)}
        dpg.delete_item(self.files_parent, children_only=True)
        self.file_boxes = {}
        files = br.result_files()
        if not before and files:
            before = {files[0].name}
        for p in files:
            self.file_boxes[p.name] = dpg.add_checkbox(label=p.name, default_value=p.name in before,
                                                       parent=self.files_parent, callback=self.show_results)
        if not files:
            dpg.add_text("No result files.", color=MUTED, parent=self.files_parent)
        self.show_results()

    def show_results(self, *_) -> None:
        if not dpg.does_item_exist(self.results_parent):
            return
        dpg.delete_item(self.results_parent, children_only=True)
        p = self.results_parent
        rows = br.read_rows(self.checked())
        if not rows:
            dpg.add_text("Select a result file, or start a run from Configuration.", color=MUTED, parent=p)
            return
        s = br.summarize(rows)
        unit = s["unit"]
        st.font(dpg.add_text(f"{len(rows)} runs  ·  {len(s['tasks'])} task(s)  ·  models: {', '.join(s['models'])}"
                             f"  ·  cost unit: {unit}", parent=p), "semibold")
        st.font(dpg.add_text("Rerun: execution after the site change, with the plan from the cold run restored. "
                             "Cost ratio: mean rerun cost relative to Ecogent. Repairs persisted: second reruns with zero LLM calls.", color=MUTED, wrap=740, parent=p), "small")
        dpg.add_spacer(height=4, parent=p)
        st.section_label("Summary by system", parent=p)
        with dpg.table(parent=p, header_row=True, policy=dpg.mvTable_SizingFixedFit, borders_innerH=True,
                       row_background=True, scrollX=True, height=_table_h(len(s["overview"]))):
            for c in ("System", "Success", "LLM calls", "Total cost", "Cold-run cost", "Mean rerun cost", "Cost ratio",
                      "LLM calls / rerun", "Time / rerun (s)", "Repairs persisted", "Timeouts"):
                dpg.add_table_column(label=c)
            for o in s["overview"]:
                with dpg.table_row():
                    dpg.add_text(o["variant"])
                    ok = o["passed"] == o["runs"]
                    dpg.add_text(f"{o['passed']} / {o['runs']}", color=SUCCESS if ok else DANGER if not o["passed"] else WARN)
                    dpg.add_text(str(o["calls"]))
                    dpg.add_text(br.fmt_cost(o["total"], unit))
                    dpg.add_text(br.fmt_cost(o["cold"], unit))
                    dpg.add_text(br.fmt_cost(o["rerun"], unit))
                    dpg.add_text("-" if o["vs_ecogent"] is None else f"{o['vs_ecogent']:.1f}x")
                    dpg.add_text("-" if o["rerun_calls"] is None else f"{o['rerun_calls']:.1f}")
                    dpg.add_text("-" if o["seconds"] is None else f"{o['seconds']:.0f}")
                    z, n = o["rerun2_zero"]
                    dpg.add_text(f"{z} / {n}" if n else "-")
                    dpg.add_text(str(o["timeouts"]), color=DANGER if o["timeouts"] else MUTED)
        dpg.add_spacer(height=6, parent=p)
        st.section_label("Reruns by level  (successes / runs  ·  mean cost  ·  mean LLM calls)", parent=p)
        with dpg.table(parent=p, header_row=True, policy=dpg.mvTable_SizingFixedFit, borders_innerH=True,
                       row_background=True, scrollX=True, height=_table_h(len(s["by_level"]))):
            dpg.add_table_column(label="System")
            for lv in s["levels"]:
                dpg.add_table_column(label=f"L{lv}")
            for b in s["by_level"]:
                with dpg.table_row():
                    dpg.add_text(b["variant"])
                    for lv in s["levels"]:
                        c = b["cells"].get(lv)
                        if not c:
                            dpg.add_text("-", color=MUTED)
                            continue
                        col = SUCCESS if c["pass"] == c["n"] else DANGER if not c["pass"] else WARN
                        dpg.add_text(f"{c['pass']}/{c['n']}  ·  {br.fmt_cost(c['cost'], unit)}  ·  {c['calls']:.1f}",
                                     color=col)
        dpg.add_spacer(height=6, parent=p)
        st.section_label(f"Runs ({min(len(rows), 300)} of {len(rows)}, chronological)", parent=p)
        with dpg.table(parent=p, header_row=True, policy=dpg.mvTable_SizingFixedFit, borders_innerH=True,
                       row_background=True, scrollX=True, scrollY=True, height=320):
            for c in ("Task", "System", "Seed", "Level", "Phase", "Status", "Success", "Oracle verdict", "LLM calls", "Cost", "Time (s)"):
                dpg.add_table_column(label=c)
            for r in rows[-300:]:
                with dpg.table_row():
                    for k in ("task", "variant", "seed", "level", "phase", "status"):
                        dpg.add_text(str(r.get(k, "")))
                    dpg.add_text("yes" if r.get("success") == "1" else "no",
                                 color=SUCCESS if r.get("success") == "1" else DANGER)
                    dpg.add_text(st.truncate(r.get("oracle", ""), 38))
                    dpg.add_text(str(r.get("calls", "")))
                    dpg.add_text(br.fmt_cost(r.get("_cost"), unit))
                    dpg.add_text(str(r.get("seconds", "")))

    # ------------------------------------------------------------------ run tab
    def _run_buttons(self) -> None:
        with dpg.group(horizontal=True):
            self.run_btn = dpg.add_button(label="Start", width=130, callback=self._run_now)
            dpg.bind_item_theme(self.run_btn, "btn_primary")
            self.stop_btn = dpg.add_button(label="Stop", width=90, callback=lambda: self.ctl.stop())
            dpg.bind_item_theme(self.stop_btn, "btn_danger")
            dpg.bind_item_theme(dpg.add_button(label="Save configuration", callback=self._save), "btn_secondary")
            dpg.add_spacer(width=20)
            st.font(dpg.add_text("Validation:", color=MUTED), "small")
            helps = {"Lab integrity test": "Lab sites, drift invariants and oracles (no browser).",
                     "Pipeline test (mock LLM)": "The complete drift_bench pipeline with a scripted mock LLM.",
                     "Shop oracle test": "Shop oracles: correct answers pass; empty and stale answers fail (starts the shop server).",
                     "Lab visual invariance test": "Lab level 1 (markup-only change) renders pixel-identical to level 0."}
            for label, help_text in helps.items():
                b = dpg.add_button(label=label, user_data=label, callback=lambda s, a, u: self._free(u))
                dpg.bind_item_theme(b, "btn_secondary")
                with dpg.tooltip(b):
                    dpg.add_text("No API cost. " + help_text)
        self.msg = dpg.add_text("", color=WARN)

    def _free(self, label: str) -> None:
        self.ctl.free_check(label)
        dpg.set_value(self.tab_bar, self.tabs["output"])
        self.update_state()

    def _build_output(self) -> None:
        self.state_text2 = dpg.add_text("", color=MUTED)
        self.console = dpg.add_input_text(multiline=True, readonly=True, width=-1, height=-1,
                                          default_value="\n".join(self.ctl.lines()))
        st.font(self.console, "mono")

    def _build_run(self) -> None:
        c = self.cfg
        self._run_buttons()
        self.state_text = dpg.add_text("", color=MUTED)
        with dpg.child_window(height=-1, border=False):
            dpg.bind_item_theme(dpg.last_item(), "flat")
            with dpg.group(horizontal=True):
                st.section_label("Environment")
                self.site = dpg.add_radio_button(["lab", "shop"], default_value=c.get("site", "lab"), horizontal=True,
                                                 callback=self._site_changed)
                st.font(dpg.add_text("lab: bench/lab sites, levels 0-4 (cumulative)  ·  shop: test shop (held-out), "
                                     "levels 0-9 (one change type each)", color=MUTED), "small")
            with dpg.group(horizontal=True):
                st.section_label("Tasks")
                dpg.add_button(label="All", small=True, callback=lambda: self._set_all(self.task_boxes, True))
                dpg.add_button(label="None", small=True, callback=lambda: self._set_all(self.task_boxes, False))
            self.task_boxes: dict[str, int] = {}
            self.task_parent = dpg.add_group()
            self._build_task_grid(c.get("site", "lab"), c["tasks"])
            st.section_label("Systems")
            self.var_boxes: dict[str, int] = {}
            with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchSame):
                for _ in range(4):
                    dpg.add_table_column()
                for i in range(0, len(br.VARIANTS), 4):
                    with dpg.table_row():
                        for v in br.VARIANTS[i:i + 4]:
                            self.var_boxes[v] = dpg.add_checkbox(label=v, default_value=v in c["variants"],
                                                                 callback=self.update_state)
                            with dpg.tooltip(self.var_boxes[v]):
                                dpg.add_text(VARIANT_HELP.get(v, v))
            dpg.add_spacer(height=2)
            with dpg.group(horizontal=True, horizontal_spacing=18):
                self.levels = dpg.add_input_text(label="Drift levels", default_value=c["levels"], width=110,
                                                 callback=self.update_state)
                self.seeds = dpg.add_input_text(label="Seeds", default_value=c["seeds"], width=80, callback=self.update_state)
                self.repeats = dpg.add_input_int(label="Repeats", default_value=int(c["repeats"]), width=90,
                                                 min_value=1, min_clamped=True, callback=self.update_state)
                self.out_name = dpg.add_input_text(label="Result name", default_value=c["out_name"], width=150,
                                                   callback=self.update_state)
            with dpg.group(horizontal=True, horizontal_spacing=18):
                self.prices = dpg.add_input_text(label="Pricing", default_value=c["prices"], width=380,
                                                 callback=self.update_state,
                                                 hint="MODEL=IN,OUT,CACHED per 1M tokens; several: separate with ;")
                self.max_steps = dpg.add_input_int(label="Step limit (external agents)", default_value=int(c["max_steps"]),
                                                   width=90, callback=self.update_state)
                self.timeout = dpg.add_input_int(label="Timeout, s (external agents)", default_value=int(c["timeout"]),
                                                 width=90, callback=self.update_state)
            with dpg.group(horizontal=True, horizontal_spacing=18):
                self.price_date = dpg.add_input_text(label="Pricing date", hint="YYYY-MM-DD",
                                                     default_value=c.get("price_date", ""), width=120, callback=self.update_state)
            with dpg.group(horizontal=True, horizontal_spacing=18):
                self.headless = dpg.add_checkbox(label="Headless browser", default_value=bool(c["headless"]),
                                                 callback=self.update_state)
                self.no_rerun2 = dpg.add_checkbox(label="Skip second rerun", default_value=bool(c["no_rerun2"]),
                                                  callback=self.update_state)
            self.plan_text = dpg.add_text("", color=MUTED, wrap=1000)
            self.cmd_text = dpg.add_input_text(default_value="", readonly=True, width=-1)
            st.font(self.cmd_text, "mono")

    def _build_task_grid(self, site: str, selected: list) -> None:
        dpg.delete_item(self.task_parent, children_only=True)
        self.task_boxes = {}
        names = br.task_names(site)
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchSame, parent=self.task_parent):
            for _ in range(4):
                dpg.add_table_column()
            for i in range(0, len(names), 4):
                with dpg.table_row():
                    for n in names[i:i + 4]:
                        self.task_boxes[n] = dpg.add_checkbox(label=n, default_value=n in selected, callback=self.update_state)

    def _site_changed(self, *_) -> None:
        site = dpg.get_value(self.site)
        names = br.task_names(site)
        self._build_task_grid(site, names[:1])
        dpg.set_value(self.levels, ",".join(str(k) for k in br.SITE_LEVELS[site]))
        self.update_state()

    @staticmethod
    def _set_all(boxes: dict, value: bool) -> None:
        for b in boxes.values():
            dpg.set_value(b, value)

    def read_form(self) -> dict:
        c = dict(self.cfg)
        c.update(site=dpg.get_value(self.site), price_date=dpg.get_value(self.price_date).strip(),
                 tasks=[n for n, b in self.task_boxes.items() if dpg.get_value(b)],
                 variants=[v for v, b in self.var_boxes.items() if dpg.get_value(b)],
                 levels=dpg.get_value(self.levels).strip(), seeds=dpg.get_value(self.seeds).strip(),
                 repeats=max(1, dpg.get_value(self.repeats)), prices=dpg.get_value(self.prices).strip(),
                 out_name=dpg.get_value(self.out_name).strip(), max_steps=dpg.get_value(self.max_steps),
                 timeout=dpg.get_value(self.timeout), headless=dpg.get_value(self.headless),
                 no_rerun2=dpg.get_value(self.no_rerun2))
        if hasattr(self, "mode"):
            c["schedule"] = {"mode": dpg.get_value(self.mode), "date": dpg.get_value(self.date).strip(),
                             "time": dpg.get_value(self.time).strip(), "weekday": dpg.get_value(self.weekday),
                             "only_when_idle": dpg.get_value(self.idle)}
        return c

    def update_state(self, *_) -> None:
        if not dpg.does_item_exist(self.tag) or not hasattr(self, "run_btn"):
            return
        c = self.read_form()
        errs = br.validate(c)
        cells, runs = br.count_runs(c)
        dpg.set_value(self.plan_text, "  ".join(errs) if errs else
                      f"{cells} cell(s), {runs} run(s)  ->  bench/results/{c['out_name']}.csv  (rows are appended; "
                      f"use a new result name for a separate experiment)")
        dpg.configure_item(self.plan_text, color=DANGER if errs else MUTED)
        dpg.set_value(self.cmd_text, " ".join(br.command(c, self.settings)[1:]) if not errs else "")
        running = self.ctl.running()
        dpg.configure_item(self.run_btn, enabled=not running and not errs)
        dpg.configure_item(self.stop_btn, enabled=running)
        state = (f"Running: {self.ctl.label()}  (since {self.ctl.started()})  -  see Log"
                 if running else f"Idle.  Schedule: {br.describe_schedule(self.cfg)}")
        dpg.set_value(self.state_text, state)
        dpg.set_value(self.state_text2, state.split("  -  see Log")[0])
        dpg.configure_item(self.state_text, color=st.PRIMARY_HOVER if running else MUTED)
        if hasattr(self, "sched_info"):
            self._update_schedule_info()

    def _save(self, *_) -> None:
        c = self.read_form()
        errs = br.validate(c) + ([br.schedule_error(c)] if br.schedule_error(c) else [])
        if errs:
            dpg.set_value(self.msg, errs[0])
            return
        self.cfg = c
        br.save_config(self.settings, c)
        self.cfg = br.load_config(self.settings)
        dpg.set_value(self.msg, "Saved.")
        self.update_state()

    def _run_now(self, *_) -> None:
        c = self.read_form()
        if br.validate(c):
            return
        cells, runs = br.count_runs(c)
        ext = [v for v in c["variants"] if v in br.EXTERNAL]
        msg = (f"Start the benchmark?\n\n{runs} runs in {cells} cells with your main model from Settings. "
               f"This uses the paid API.\n"
               + ("A browser window opens for each cell; do not interact with it.\n" if not c["headless"] else "")
               + (f"External agents: {', '.join(ext)} (their installs must be ready).\n" if ext else "")
               + "Do not run Ecogent tasks in the app at the same time.")

        def go(yes: bool) -> None:
            if yes:
                self.cfg = c
                br.save_config(self.settings, c)
                self.ctl.start(c, scheduled=False)
                if dpg.does_item_exist(self.tab_bar):
                    dpg.set_value(self.tab_bar, self.tabs["output"])
                self.update_state()
        ConfirmDialog(msg, go)

    # ------------------------------------------------------------------ schedule tab
    def _build_schedule(self) -> None:
        s = self.cfg["schedule"]
        st.font(dpg.add_text("Automatic runs use the saved configuration. The application must be open at the scheduled time; "
                             "a run that falls due while a task is running is deferred until it finishes.", color=MUTED, wrap=1000), "small")
        dpg.add_spacer(height=6)
        self.mode = dpg.add_radio_button(br.SCHEDULE_MODES, default_value=s.get("mode", "off"), horizontal=True,
                                         callback=self.update_state)
        with dpg.group(horizontal=True, horizontal_spacing=18):
            self.date = dpg.add_input_text(label="Date (once)", default_value=s.get("date", ""), hint="YYYY-MM-DD",
                                           width=130, callback=self.update_state)
            self.time = dpg.add_input_text(label="Time", default_value=s.get("time", "02:00"), hint="HH:MM", width=80,
                                           callback=self.update_state)
            self.weekday = dpg.add_combo(br.WEEKDAYS, label="Day (weekly)", default_value=s.get("weekday", "Sun"),
                                         width=80, callback=self.update_state)
        self.idle = dpg.add_checkbox(label="Defer while a task is running", default_value=s.get("only_when_idle", True))
        with dpg.group(horizontal=True):
            dpg.bind_item_theme(dpg.add_button(label="Save schedule", width=150, callback=self._save), "btn_primary")
        dpg.add_spacer(height=6)
        self.sched_info = dpg.add_text("", wrap=1000)
        st.font(dpg.add_text("Scheduled runs use the paid API and a visible browser unless Headless browser is selected. "
                             "The lab sites have no CAPTCHAs, so no supervision is required.",
                             color=MUTED, wrap=1000), "small")

    def _update_schedule_info(self) -> None:
        saved = br.load_config(self.settings)
        pending = self.read_form()
        err = br.schedule_error(pending)
        nxt = br.next_run_iso(pending)
        txt = (f"Saved: {br.describe_schedule(saved)}\nNext run: {saved.get('next_run') or '-'}    "
               f"Last run: {saved.get('last_run') or '-'}")
        if err:
            txt += f"\n{err}"
        elif pending.get("schedule") != saved.get("schedule"):
            txt += f"\nNot saved yet - with these values the next run would be: {nxt or '-'}"
        dpg.set_value(self.sched_info, txt)
        dpg.configure_item(self.sched_info, color=DANGER if err else st.TEXT)

    # ------------------------------------------------------------------ live output
    def append(self, line: str) -> None:
        if dpg.does_item_exist(self.tag) and hasattr(self, "console"):
            dpg.set_value(self.console, "\n".join(self.ctl.lines()))


class BenchControls:
    """What the window needs from the app (EcogentApp fills these in)."""

    def __init__(self, start: Callable[[dict, bool], None], stop: Callable[[], None], free_check: Callable[[str], None],
                 summary: Callable[[list], None], figures: Callable[[list], None], open_results: Callable[[], None],
                 running: Callable[[], bool], label: Callable[[], str], started: Callable[[], str],
                 lines: Callable[[], list], open_file: Callable = lambda p: None, report_done: Callable = lambda p, e: None):
        self.start, self.stop, self.free_check = start, stop, free_check
        self.summary, self.figures, self.open_results = summary, figures, open_results
        self.running, self.label, self.started, self.lines = running, label, started, lines
        self.open_file, self.report_done = open_file, report_done     # report_done is called from a worker thread
