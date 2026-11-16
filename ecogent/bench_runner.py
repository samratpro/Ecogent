"""
Benchmark support for the app's Benchmark window (no GUI code here, so it can be tested alone).

- config: what the automatic benchmark runs and when (<home>/bench_config.json)
- command: the bench/drift_bench.py command line built from that config
- schedule: off / once / daily / weekly, checked by BenchScheduler (a background thread)
- results: CSVs in bench/results summarized per system and per drift level (pure Python)
- BenchProcess: runs one benchmark (or a free check) as a subprocess and streams its output

The benchmark itself is unchanged: the app only starts bench/drift_bench.py with arguments, exactly
as from a terminal, so every number in the window comes from the same CSV the paper uses.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .config import ABLATIONS, Settings
from .storage import read_json, write_json

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "bench"
RESULTS = BENCH / "results"
INTERNAL = ["ecogent", "nocache", "compile_only", "no_cheap"]
EXTERNAL = ["stagehand", "browser_use", "browser_use_novision"]
VARIANTS = INTERNAL + EXTERNAL + sorted(a for a in ABLATIONS if a != "no_repair")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SCHEDULE_MODES = ["off", "once", "daily", "weekly"]
BENCH_DEBUG_PORT_OFFSET = 40          # the benchmark browser must not take the app browser's debug port

DEFAULT_CONFIG = {
    "site": "lab",
    "price_date": "",
    "tasks": ["papers_caching"],
    "variants": ["ecogent", "nocache", "compile_only", "stagehand", "browser_use"],
    "levels": "0,1,2,3,4",
    "seeds": "1",
    "repeats": 1,
    "prices": "gpt-4o-mini=0.15,0.60,0.075",
    "out_name": "gui_run",
    "max_steps": 30,
    "timeout": 420,
    "headless": False,
    "no_rerun2": False,
    "schedule": {"mode": "off", "date": "", "time": "02:00", "weekday": "Sun", "only_when_idle": True},
    "last_run": "",
    "next_run": "",
}


def available() -> bool:
    return (BENCH / "drift_bench.py").exists()


# ----------------------------------------------------------------------------- config
def config_path(settings: Settings) -> Path:
    return settings.home_path / "bench_config.json"


def load_config(settings: Settings) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    saved = read_json(config_path(settings), {})
    if isinstance(saved, dict):
        sched = {**cfg["schedule"], **(saved.get("schedule") or {})}
        cfg.update(saved)
        cfg["schedule"] = sched
    return cfg


def save_config(settings: Settings, cfg: dict) -> None:
    cfg["next_run"] = next_run_iso(cfg)
    write_json(config_path(settings), cfg)


SITE_LEVELS = {"lab": {0: "none", 1: "attributes", 2: "structure", 3: "text", 4: "redesign"},
               "shop": {0: "baseline", 1: "markup-rebuild", 2: "markup-refactor", 3: "markup-per-load", 4: "navigation",
                        5: "redesign", 6: "copy", 7: "interstitials", 8: "data", 9: "combined"}}


def task_names(site: str = "lab") -> list[str]:
    """Task names of a site (bench/lab/tasks.py or bench/shop_tasks.py); empty when bench/ is not there."""
    if not available():
        return []
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        if site == "shop":
            from bench.shop_tasks import TASKS
        else:
            from bench.lab.tasks import TASKS
        return [t.name for t in TASKS]
    except Exception:  # noqa: BLE001 - the window must open even if the tasks cannot be imported
        return []


def _ints(text: str, what: str) -> list[int]:
    try:
        vals = [int(x) for x in str(text).replace(" ", "").split(",") if x != ""]
    except ValueError:
        raise ValueError(f"{what}: use numbers separated by commas, e.g. 0,1,2") from None
    if not vals:
        raise ValueError(f"{what}: at least one number is needed")
    return vals


def validate(cfg: dict) -> list[str]:
    """Problems that would make the run fail; empty = runnable."""
    errs = []
    if not cfg.get("tasks"):
        errs.append("Pick at least one task.")
    if not cfg.get("variants"):
        errs.append("Pick at least one system.")
    for key, what in (("levels", "Drift levels"), ("seeds", "Seeds")):
        try:
            vals = _ints(cfg.get(key, ""), what)
            top = max(SITE_LEVELS.get(cfg.get("site", "lab"), SITE_LEVELS["lab"]))
            if key == "levels" and any(v < 0 or v > top for v in vals):
                errs.append(f"Drift levels must be between 0 and {top} for this site.")
        except ValueError as e:
            errs.append(str(e))
    for p in [x.strip() for x in str(cfg.get("prices", "")).split(";") if x.strip()]:
        if not re.match(r"^[^=\s]+=\s*[\d.]+\s*,\s*[\d.]+(\s*,\s*[\d.]+)?$", p):
            errs.append(f"Price '{p}': use MODEL=IN,OUT[,CACHED] (USD per 1M tokens).")
    if not re.match(r"^[\w.-]+$", str(cfg.get("out_name", ""))):
        errs.append("Result name: letters, digits, '-', '_' or '.' only.")
    return errs


def out_csv(cfg: dict) -> Path:
    return RESULTS / f"{cfg.get('out_name') or 'gui_run'}.csv"


def command(cfg: dict, settings: Settings) -> list[str]:
    """The drift_bench.py command line for this config (same as typing it in a terminal)."""
    cmd = [sys.executable, "-u", str(BENCH / "drift_bench.py"), "--site", cfg.get("site", "lab"),
           "--tasks", ",".join(cfg["tasks"]), "--variants", ",".join(cfg["variants"]),
           "--levels", str(cfg["levels"]).replace(" ", ""), "--seeds", str(cfg["seeds"]).replace(" ", ""),
           "--repeats", str(int(cfg.get("repeats") or 1)), "--out", str(out_csv(cfg)),
           "--max-steps", str(int(cfg.get("max_steps") or 30)), "--timeout", str(int(cfg.get("timeout") or 420)),
           "--debug-port", str(settings.debug_port + BENCH_DEBUG_PORT_OFFSET)]
    for p in [x.strip() for x in str(cfg.get("prices", "")).split(";") if x.strip()]:
        cmd += ["--price", p.replace(" ", "")]
    if cfg.get("headless"):
        cmd.append("--headless")
    if cfg.get("no_rerun2"):
        cmd.append("--no-rerun2")
    if cfg.get("meta"):
        cmd += ["--meta", str(cfg["meta"])]
    return cmd


def count_runs(cfg: dict) -> tuple[int, int]:
    """(cells, runs) the config will execute - shown before a run starts."""
    try:
        levels = len(_ints(cfg["levels"], "levels"))
        seeds = len(_ints(cfg["seeds"], "seeds"))
    except (ValueError, KeyError):
        return 0, 0
    per_seed = len(cfg.get("tasks") or []) * seeds * int(cfg.get("repeats") or 1)
    cells = runs = 0
    for v in cfg.get("variants") or []:
        cells += per_seed
        twice = v not in ("nocache", "browser_use", "browser_use_novision") and not cfg.get("no_rerun2")
        runs += per_seed * (1 + levels * (2 if twice else 1))
    return cells, runs


def free_check_commands(scratch: Path) -> dict[str, list[str]]:
    """No-cost checks: the lab self-test and the fake-LLM plumbing run of drift_bench."""
    return {"Lab integrity test": [sys.executable, "-u", "-m", "bench.lab.selftest"],
            "Pipeline test (mock LLM)": [sys.executable, "-u", "-m", "bench.lab.fake_run", str(scratch)],
            "Shop oracle test": [sys.executable, "-u", "-m", "bench.shop_selftest"],
            "Lab visual invariance test": [sys.executable, "-u", "-m", "bench.lab.look_check"]}


# ----------------------------------------------------------------------------- schedule
def _at(day: datetime, hhmm: str) -> datetime:
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", (hhmm or "").strip())
    if not m:
        raise ValueError(f"time must be HH:MM, got {hhmm!r}")
    return day.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)


def next_run(cfg: dict, now: Optional[datetime] = None) -> Optional[datetime]:
    """Next due time of the schedule, or None when it is off / already used / invalid."""
    now = now or datetime.now()
    s = cfg.get("schedule") or {}
    mode = s.get("mode", "off")
    try:
        if mode == "once":
            t = _at(datetime.strptime(s.get("date", ""), "%Y-%m-%d"), s.get("time", ""))
            last = cfg.get("last_run") or ""
            return None if last and datetime.fromisoformat(last) >= t else t
        if mode == "daily":
            t = _at(now, s.get("time", ""))
            return t if t > now else t + timedelta(days=1)
        if mode == "weekly":
            wd = WEEKDAYS.index(s.get("weekday", "Sun"))
            t = _at(now, s.get("time", "")) + timedelta(days=(wd - now.weekday()) % 7)
            return t if t > now else t + timedelta(days=7)
    except (ValueError, TypeError):
        return None
    return None


def next_run_iso(cfg: dict) -> str:
    t = next_run(cfg)
    return t.isoformat(timespec="seconds") if t else ""


def schedule_error(cfg: dict) -> str:
    s = cfg.get("schedule") or {}
    if s.get("mode", "off") == "off":
        return ""
    try:
        _at(datetime.now(), s.get("time", ""))
    except ValueError:
        return "Schedule: time must be HH:MM (00:00-23:59)."
    if s.get("mode") == "once":
        try:
            day = datetime.strptime(s.get("date", ""), "%Y-%m-%d")
        except ValueError:
            return "Schedule: date must be YYYY-MM-DD."
        if _at(day, s.get("time", "")) <= datetime.now():
            return "Schedule: that date and time are already past."
    return ""


def describe_schedule(cfg: dict) -> str:
    s = cfg.get("schedule") or {}
    mode = s.get("mode", "off")
    if mode == "off":
        return "off (runs only when you press Run now)"
    when = {"once": f"once on {s.get('date')} at {s.get('time')}", "daily": f"every day at {s.get('time')}",
            "weekly": f"every {s.get('weekday')} at {s.get('time')}"}[mode]
    return when + (" (waits while Ecogent is busy)" if s.get("only_when_idle", True) else "")


class BenchScheduler(threading.Thread):
    """Checks the saved schedule every interval_s seconds and calls on_due() while a run is due.
    on_due (app side) starts the run and calls mark_started, which moves next_run forward; if the
    app is busy it does nothing and the run is tried again on the next check."""

    def __init__(self, settings_getter: Callable[[], Settings], on_due: Callable[[], None], interval_s: int = 20):
        super().__init__(daemon=True, name="ecogent-bench-scheduler")
        self.settings_getter, self.on_due, self.interval_s = settings_getter, on_due, interval_s
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                cfg = load_config(self.settings_getter())
                due = cfg.get("next_run") and datetime.fromisoformat(cfg["next_run"]) <= datetime.now()
            except (ValueError, TypeError):
                due = False
            if due:
                self.on_due()


def mark_started(settings: Settings, cfg: dict) -> None:
    cfg["last_run"] = datetime.now().isoformat(timespec="seconds")
    save_config(settings, cfg)          # recomputes next_run (a "once" schedule ends here)


# ----------------------------------------------------------------------------- results
def result_files() -> list[Path]:
    if not RESULTS.exists():
        return []
    return sorted((p for p in RESULTS.glob("*.csv")), key=lambda p: p.stat().st_mtime, reverse=True)


def read_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        try:
            with open(p, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    r["_file"] = p.name
                    rows.append(r)
        except (OSError, csv.Error):
            continue
    return rows


def _f(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mean(vals: list) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def summarize(rows: list[dict]) -> dict:
    """Overview per system and pass-rate / cost per drift level (reruns), plus the unit used.
    Cost is USD when every row is priced, otherwise input+output tokens."""
    priced = bool(rows) and all(r.get("cost_usd") not in ("", None) for r in rows)
    for r in rows:
        r["_cost"] = _f(r.get("cost_usd")) if priced else \
            (_f(r.get("input_tokens")) or 0) + (_f(r.get("output_tokens")) or 0)
        if r.get("status") == "timeout" and not int(_f(r.get("calls")) or 0):
            r["_cost"] = None           # killed before it reported usage: unknown, not free
    by_var = defaultdict(list)
    for r in rows:
        by_var[r.get("variant", "?")].append(r)
    order = sorted(by_var, key=lambda v: (VARIANTS.index(v) if v in VARIANTS else 99, v))
    overview = []
    for v in order:
        rs = by_var[v]
        reruns = [r for r in rs if r.get("phase") == "rerun"]
        rerun2 = [r for r in rs if r.get("phase") == "rerun2"]
        overview.append({
            "variant": v, "runs": len(rs), "passed": sum(r.get("success") == "1" for r in rs),
            "calls": sum(int(_f(r.get("calls")) or 0) for r in rs),
            "total": sum(r["_cost"] for r in rs if r["_cost"] is not None)
                     if any(r["_cost"] is not None for r in rs) else None,
            "cold": _mean([r["_cost"] for r in rs if r.get("phase") == "cold"]),
            "rerun": _mean([r["_cost"] for r in reruns]),
            "rerun_calls": _mean([_f(r.get("calls")) for r in reruns]),
            "seconds": _mean([_f(r.get("seconds")) for r in reruns]),
            "rerun2_zero": (sum(int(_f(r.get("calls")) or 0) == 0 for r in rerun2), len(rerun2)),
            "timeouts": sum(r.get("status") == "timeout" for r in rs),
        })
    ref = next((o for o in overview if o["variant"] == "ecogent"), None)
    for o in overview:
        o["vs_ecogent"] = (o["rerun"] / ref["rerun"]) if ref and ref["rerun"] and o["rerun"] is not None else None
    levels = sorted({int(r["level"]) for r in rows if str(r.get("level", "")).isdigit()})
    by_level = []
    for v in order:
        cells = {}
        for lv in levels:
            rs = [r for r in by_var[v] if r.get("phase") == "rerun" and r.get("level") == str(lv)]
            if rs:
                cells[lv] = {"n": len(rs), "pass": sum(r.get("success") == "1" for r in rs),
                             "cost": _mean([r["_cost"] for r in rs]), "calls": _mean([_f(r.get("calls")) for r in rs])}
        by_level.append({"variant": v, "cells": cells})
    return {"unit": "USD" if priced else "tokens", "overview": overview, "levels": levels, "by_level": by_level,
            "tasks": sorted({r.get("task", "") for r in rows}), "models": sorted({r.get("main_model", "") for r in rows})}


def fmt_cost(v: Optional[float], unit: str) -> str:
    if v is None:
        return "-"
    return f"${v:.4f}" if unit == "USD" else f"{v:,.0f} tok"


# ----------------------------------------------------------------------------- subprocess
class BenchProcess:
    """One benchmark or free check at a time, as a subprocess; output lines go to on_line,
    the exit code to on_exit (both called from a reader thread)."""

    def __init__(self, on_line: Callable[[str], None], on_exit: Callable[[str, int], None]):
        self.on_line, self.on_exit = on_line, on_exit
        self.proc: Optional[subprocess.Popen] = None
        self.label = ""
        self.started = ""

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, label: str, cmd: list[str]) -> None:
        if self.running:
            raise RuntimeError(f"'{self.label}' is still running")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(REPO)}
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(cmd, cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                     bufsize=1, creationflags=flags)
        self.label, self.started = label, datetime.now().isoformat(timespec="seconds")
        threading.Thread(target=self._read, args=(self.proc, label), daemon=True, name="ecogent-bench-io").start()

    def _read(self, proc: subprocess.Popen, label: str) -> None:
        for line in proc.stdout:
            if line.strip():
                self.on_line(line.rstrip())
        self.on_exit(label, proc.wait())

    def stop(self) -> None:
        if not self.running:
            return
        if sys.platform == "win32":     # the whole tree: drift_bench starts browsers and node / python agents
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
        else:
            self.proc.terminate()
