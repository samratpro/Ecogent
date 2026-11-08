"""
Drift benchmark: cost and success of repeated browser tasks while the site changes.

Protocol for every (task, system variant, seed) cell, on the local lab sites (bench/lab):
  1. cold     drift level 0: a new chat solves the task from the prompt (planning, lookups, ...)
  2. for each drift level L:
       rerun    the plan compiled in step 1 is restored and run again on the site at level L
                (measures the repair cost of a change of size L)
       rerun2   run again at level L without restoring (was the repair written back? ~0 expected)
Every run is scored by the task oracle against ground truth (success, precision, recall) and
written as one CSV row with tokens, cached tokens, LLM calls by purpose, USD and seconds.
Each cell gets its own data folder, so no plan, cache or cookie leaks between cells.

System variants (--variants, comma separated):
  ecogent        the full system
  nocache        no reuse at all: every run is a new chat, plan memory and caches cleared
                 (behaves like an LLM-every-run agent; the "no reuse" baseline)
  compile_only   compiles on the cold run, never repairs on reruns (Agentic-Compilation-style)
  no_cheap       the full system with the cheap model off (main model for every job)
  <ablation>     one or more of ecogent.config.ABLATIONS joined by "+", e.g. no_refind+no_obvious
  browser_use    external baseline: browser-use (LLM decides every step; no memory -> every run fresh).
                 Needs .venv-baselines (pip install browser-use).
  stagehand      external baseline: Stagehand v3 agent with cacheDir + selfHeal (records on the cold
                 run, replays / self-heals on reruns; same restore protocol as Ecogent).
                 Needs node + bench/baselines/stagehand (npm install).
  External baselines use the main model from Settings, the same oracles and pricing. Their prompt gets
  one disclosed addition: "also give the complete result in your final answer" (Stagehand cannot write
  files) and, for automation tasks, the user's name / email (Ecogent gets them from its user-info file).

Usage (repo root; the LLMs come from your Settings; a visible browser by default):
  python bench/drift_bench.py --tasks all --variants ecogent,compile_only,nocache --levels 0,1,2,3,4 \
      --seeds 1,2,3 --price gpt-4o-mini=0.15,0.60,0.075 --price claude-sonnet-5-5=3,15,0.3 \
      --out bench/results/drift.csv
  python bench/summarize.py bench/results/drift.csv

Prices: --price MODEL=IN,OUT[,CACHED] in USD per 1M tokens; MODEL as recorded in usage
("provider:model" or just the model name). Rows of unpriced models get an empty cost.
A manifest (arguments, models, git commit, time) is written next to the CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ecogent.bridge import HeadlessBridge          # noqa: E402
from ecogent.config import ABLATIONS, Settings     # noqa: E402
from ecogent.core import EcogentAgent              # noqa: E402
from bench.lab import drift                        # noqa: E402
from bench.lab.server import LabServer             # noqa: E402
from bench.lab.tasks import BY_NAME, TASKS, USER_INFO   # noqa: E402

FIELDS = ["task", "type", "variant", "seed", "repeat", "level", "level_name", "phase", "status", "success", "precision",
          "recall", "oracle", "seconds", "calls", "input_tokens", "cached_input_tokens", "output_tokens",
          "cost_usd", "by_purpose", "cache_hits", "local_heals", "local_picks", "llm_lookups", "healed",
          "rescued", "steps_ok", "steps_failed", "steps_skipped", "main_model", "cheap_model", "chat_id", "time"]
SPECIAL = {"ecogent", "nocache", "compile_only", "no_cheap"}
EXTERNAL = {"browser_use", "stagehand"}
BASELINES = ROOT / "bench" / "baselines"


class BenchBridge(HeadlessBridge):
    """Answers the agent's questions the same way in every run: samples accepted, user info from
    tasks.USER_INFO, no schedules / profile setup. A hold (captcha) waits for the person at the
    visible browser when --interactive, otherwise the run fails (and is reported as failed)."""

    def __init__(self, printer, interactive: bool):
        super().__init__(printer)
        self.interactive = interactive

    def request(self, kind: str, chat_id: str = "", **payload):
        if kind == "sample":
            return {"ok": True, "comment": ""}
        if kind == "choose":
            return payload.get("default")
        if kind == "user_info":
            return {f: USER_INFO.get(f, "test") for f in payload.get("fields", [])}
        if kind == "hold" and self.interactive:
            print(f"\n[benchmark needs you] {payload.get('message', '')}", file=sys.stderr)
            input("Handle it in the browser window, then press Enter here... ")
            return True
        if kind == "confirm":
            return False                    # budget overrun, schedule offers, profile setup
        return None


# ----------------------------------------------------------------------------- variants
def variant_settings(base: Settings, variant: str) -> Settings:
    s = Settings._from_dict(json.loads(json.dumps(_asdict(base))))
    s.ablate = []
    if variant in EXTERNAL:
        return s
    if variant == "compile_only":
        s.ablate = ["no_repair"]
    elif variant == "no_cheap":
        s.cheap_llm.provider = "none"
    elif variant not in SPECIAL:
        flags = variant.split("+")
        unknown = [f for f in flags if f not in ABLATIONS]
        if unknown:
            raise SystemExit(f"unknown variant/ablation {unknown}; known: {sorted(SPECIAL | set(ABLATIONS))}")
        s.ablate = flags
    s.use_vector_memory = False             # each cell has its own home; exact-repeat memory still works
    s.default_profile = ""                  # a fresh temporary browser profile per cell
    return s


def _asdict(s: Settings) -> dict:
    from dataclasses import asdict
    return asdict(s)


# ----------------------------------------------------------------------------- measuring
def usage(s) -> dict:
    u = s.usage or {}
    return {"calls": u.get("calls", 0), "input_tokens": u.get("input_tokens", 0),
            "cached_input_tokens": u.get("cached_input_tokens", 0), "output_tokens": u.get("output_tokens", 0),
            "by_purpose": json.loads(json.dumps(u.get("by_purpose", {})))}


def delta(a: dict, b: dict) -> dict:
    d = {k: b[k] - a[k] for k in ("calls", "input_tokens", "cached_input_tokens", "output_tokens")}
    d["by_purpose"] = {}
    for p, v in b["by_purpose"].items():
        o = a["by_purpose"].get(p, {})
        calls = v.get("calls", 0) - o.get("calls", 0)
        if calls:
            d["by_purpose"][p] = {"calls": calls, "model": v.get("model", ""),
                                  "in": v.get("input_tokens", 0) - o.get("input_tokens", 0),
                                  "cached": v.get("cached_input_tokens", 0) - o.get("cached_input_tokens", 0),
                                  "out": v.get("output_tokens", 0) - o.get("output_tokens", 0)}
    return d


def parse_prices(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        model, _, nums = it.partition("=")
        vals = [float(x) for x in nums.split(",") if x.strip()]
        if len(vals) < 2:
            raise SystemExit(f"bad --price {it!r}; use MODEL=IN,OUT[,CACHED]")
        out[model.strip()] = (vals[0], vals[1], vals[2] if len(vals) > 2 else vals[0])
    return out


def price_of(model: str, prices: dict):
    if model in prices:
        return prices[model]
    short = model.split(":", 1)[-1]
    return prices.get(short) or next((v for k, v in prices.items() if k.split(":", 1)[-1] == short), None)


def cost(d: dict, prices: dict, warned: set) -> str:
    total = 0.0
    for p, v in d["by_purpose"].items():
        pr = price_of(v["model"], prices)
        if pr is None:
            if v["model"] not in warned:
                warned.add(v["model"])
                print(f"  ! no --price for model {v['model']!r}: cost left empty", file=sys.stderr)
            return ""
        p_in, p_out, p_cached = pr
        total += ((v["in"] - v["cached"]) * p_in + v["cached"] * p_cached + v["out"] * p_out) / 1_000_000
    return f"{total:.6f}"


def snapshot(s) -> dict:
    return {"plan": json.loads(json.dumps(s.plan)), "task": json.loads(json.dumps(s.current_task))}


def restore(s, snap: dict) -> None:
    plan = json.loads(json.dumps(snap["plan"]))
    data = plan.setdefault("data", {})
    data.pop("processed", None)             # automation dedupe: every rerun must apply again
    data.pop("output_file", None)
    s.save_plan(plan)
    s.save_task(json.loads(json.dumps(snap["task"])))


# ----------------------------------------------------------------------------- one cell
def run_cell(task, variant: str, seed: int, rep: int, levels: list[int], args, base: Settings, srv: LabServer,
             writer, fh, prices: dict, warned: set) -> None:
    home = Path(args.work) / variant / task.name / f"s{seed}r{rep}"
    shutil.rmtree(home, ignore_errors=True)
    settings = variant_settings(base, variant)
    settings.home = str(home)
    settings.headless = args.headless
    settings.ensure_dirs()
    log = (lambda t: print("    |", t, file=sys.stderr)) if args.verbose else (lambda t: None)
    agent = EcogentAgent(settings, BenchBridge(log, args.interactive))
    prompt = task.prompt.format(base=srv.base)
    main_model = f"{settings.main_llm.provider}:{settings.main_llm.model}"
    cheap_model = f"{settings.cheap_llm.provider}:{settings.cheap_llm.model}" if settings.cheap_llm.enabled else ""

    def measure(chat_id: str, level: int, phase: str, fresh: bool) -> None:
        srv.set(level, seed)
        srv.reset()
        s = agent.session(chat_id)
        before, t0 = usage(s), time.time()
        try:
            if fresh:
                agent.handle_message(chat_id, prompt)
            else:
                agent.rerun(chat_id)
        except Exception as e:              # noqa: BLE001 - one broken run must not stop the benchmark
            print(f"  ! {task.name} {variant} L{level} {phase}: {type(e).__name__}: {e}", file=sys.stderr)
        s = agent.session(chat_id)
        d = delta(before, usage(s))
        out = (s.plan.get("data") or {}).get("output_file")
        verdict = task.oracle(Path(out) if out else None, srv.state)
        stats = (s.plan.get("runs") or [{}])[-1].get("stats", {}) if not fresh or s.plan.get("runs") else {}
        row = {"task": task.name, "type": task.type, "variant": variant, "seed": seed, "repeat": rep, "level": level,
               "level_name": drift.LEVELS[level], "phase": phase, "status": s.meta.get("status"),
               "success": int(verdict["success"]), "precision": verdict["precision"], "recall": verdict["recall"],
               "oracle": verdict["detail"], "seconds": round(time.time() - t0, 1), "calls": d["calls"],
               "input_tokens": d["input_tokens"], "cached_input_tokens": d["cached_input_tokens"],
               "output_tokens": d["output_tokens"], "cost_usd": cost(d, prices, warned),
               "by_purpose": json.dumps(d["by_purpose"]), "main_model": main_model, "cheap_model": cheap_model,
               "chat_id": chat_id, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               **{k: stats.get(k, 0) for k in ("cache_hits", "local_heals", "local_picks", "llm_lookups", "healed",
                                                "rescued", "steps_ok", "steps_failed", "steps_skipped")}}
        writer.writerow(row)
        fh.flush()
        print(f"  {task.name:<20} {variant:<14} s{seed}r{rep} L{level} {phase:<6} {row['status'] or '-':<8} "
              f"ok={row['success']} p={row['precision']:.2f} r={row['recall']:.2f} calls={d['calls']:>3} "
              f"tok={d['input_tokens']:>7}/{d['output_tokens']:<6} ${row['cost_usd'] or '?'}")

    # A fresh browser profile per cell, created up front: login tasks then never stop at the
    # "set up a profile" question, and nothing leaks between cells. The lab clears its login
    # sessions before every run, so each run must log in again.
    (settings.profile_path / "bench").mkdir(parents=True, exist_ok=True)

    def new_chat() -> str:
        if variant == "nocache":
            agent.memory.index_file.unlink(missing_ok=True)
            shutil.rmtree(Path(settings.home) / "cache", ignore_errors=True)
        return agent.new_chat(task.type, title=task.name, profile="bench", headless=args.headless).id

    try:
        chat = new_chat()
        measure(chat, 0, "cold", fresh=True)
        snap = snapshot(agent.session(chat))
        for level in levels:
            if variant == "nocache":
                chat = new_chat()           # no reuse: every run starts from the prompt again
                measure(chat, level, "rerun", fresh=True)
                continue
            restore(agent.session(chat), snap)
            measure(chat, level, "rerun", fresh=False)
            if not args.no_rerun2:
                s = agent.session(chat)     # keep the repaired plan; only the dedupe memory is cleared,
                plan = s.plan               # because the lab job board is reset before every run
                plan.setdefault("data", {}).pop("processed", None)
                s.save_plan(plan)
                measure(chat, level, "rerun2", fresh=False)
    finally:
        agent.browser.close()


# ----------------------------------------------------------------------------- external baselines
BROWSER_CANDIDATES = [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                      r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      "/usr/bin/chromium", "/usr/bin/google-chrome",
                      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]


def find_browser(settings: Settings) -> str:
    """The same browser for every system: Settings' browser path, else the first one installed."""
    if settings.browser_path and Path(settings.browser_path).exists():
        return settings.browser_path
    return next((p for p in BROWSER_CANDIDATES if Path(p).exists()), "")


def external_prompt(task, base_url: str) -> str:
    p = task.prompt.format(base=base_url)
    if "my full name" in p:
        p += f" My full name is {USER_INFO['full_name']} and my email is {USER_INFO['email']}."
    if task.type == "scraping":
        p += " Also give the complete result in your final answer, as CSV text with a header row."
    elif task.type == "analysis":
        p += " Also give the complete report in your final answer."
    return p


def external_output(task, res: dict, run_dir: Path) -> Path | None:
    """The file the oracle scores: a file the agent wrote, else its final answer turned into one."""
    want = {"scraping": (".csv", ".json", ".xlsx"), "analysis": (".md", ".txt", ".docx", ".csv")}.get(task.type, ())
    files = [Path(f) for f in res.get("files") or [] if Path(f).suffix.lower() in want]
    if files:
        return files[0]
    text = (res.get("final_text") or "").strip()
    if not text or not want:
        return None
    if task.type == "analysis":
        out = run_dir / "final_answer.md"
        out.write_text(text, encoding="utf-8")
        return out
    import re as _re
    block = _re.search(r"```(?:csv)?\s*\n(.*?)```", text, _re.S)
    body = block.group(1) if block else "\n".join(l for l in text.splitlines() if "," in l)
    out = run_dir / "final_answer.csv"
    out.write_text(body.strip() + "\n", encoding="utf-8")
    return out


def run_external_cell(task, variant: str, seed: int, rep: int, levels: list[int], args, base: Settings,
                      srv: LabServer, writer, fh, prices: dict, warned: set) -> None:
    home = Path(args.work) / variant / task.name / f"s{seed}r{rep}"
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True, exist_ok=True)
    llm = base.main_llm
    model = f"{llm.provider}:{llm.model}"
    browser = find_browser(base)
    cache, snap = home / "stagehand_cache", home / "stagehand_cache_after_cold"
    if variant == "browser_use":
        exe = ROOT / ".venv-baselines" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        cmd_base = [str(exe), str(BASELINES / "run_browser_use.py")]
    else:
        cmd_base = ["node", str(BASELINES / "stagehand" / "run_stagehand.mjs")]
    n = {"i": 0}

    def measure(level: int, phase: str) -> None:
        srv.set(level, seed)
        srv.reset()
        n["i"] += 1
        run_dir = home / f"run{n['i']:02d}_{phase}_L{level}"
        cfg = {"prompt": external_prompt(task, srv.base), "out_dir": str(run_dir), "cache_dir": str(cache),
               "llm": {"provider": llm.provider, "model": llm.model, "base_url": llm.base_url},
               "browser": {"executable": browser, "headless": args.headless},
               "max_steps": args.max_steps, "timeout_s": args.timeout}
        run_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = run_dir / "config.json"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        env = {**__import__("os").environ, "BENCH_LLM_KEY": llm.api_key}
        t0 = time.time()
        try:
            subprocess.run([*cmd_base, str(cfg_path)], env=env, timeout=args.timeout + 120,
                           capture_output=not args.verbose, cwd=str(ROOT))
        except subprocess.TimeoutExpired:
            pass
        res_path = run_dir / "result.json"
        res = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else \
            {"status": "failed", "error": "runner wrote no result"}
        if res.get("error"):
            print(f"  ! {task.name} {variant} L{level} {phase}: {res['error'][:200]}", file=sys.stderr)
        out = external_output(task, res, run_dir)
        verdict = task.oracle(out, srv.state)
        d = {"calls": int(res.get("calls") or 0), "input_tokens": int(res.get("input_tokens") or 0),
             "cached_input_tokens": int(res.get("cached_input_tokens") or 0),
             "output_tokens": int(res.get("output_tokens") or 0)}
        d["by_purpose"] = {"agent": {"calls": d["calls"], "model": model, "in": d["input_tokens"],
                                     "cached": d["cached_input_tokens"], "out": d["output_tokens"]}} if d["calls"] else {}
        row = {"task": task.name, "type": task.type, "variant": variant, "seed": seed, "repeat": rep, "level": level,
               "level_name": drift.LEVELS[level], "phase": phase, "status": res.get("status", "failed"),
               "success": int(verdict["success"]), "precision": verdict["precision"], "recall": verdict["recall"],
               "oracle": verdict["detail"], "seconds": round(time.time() - t0, 1), **{k: d[k] for k in
               ("calls", "input_tokens", "cached_input_tokens", "output_tokens")},
               "cost_usd": cost(d, prices, warned), "by_purpose": json.dumps(d["by_purpose"]),
               "main_model": model, "cheap_model": "", "chat_id": run_dir.name,
               "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               **{k: 0 for k in ("cache_hits", "local_heals", "local_picks", "llm_lookups", "healed", "rescued",
                                 "steps_ok", "steps_failed", "steps_skipped")}}
        writer.writerow(row)
        fh.flush()
        print(f"  {task.name:<20} {variant:<14} s{seed}r{rep} L{level} {phase:<6} {row['status']:<8} "
              f"ok={row['success']} p={row['precision']:.2f} r={row['recall']:.2f} calls={d['calls']:>3} "
              f"tok={d['input_tokens']:>7}/{d['output_tokens']:<6} ${row['cost_usd'] or '?'}")

    measure(0, "cold")
    if variant == "stagehand" and cache.exists():
        shutil.copytree(cache, snap, dirs_exist_ok=True)
    for level in levels:
        if variant == "stagehand":                  # same protocol as Ecogent: restore what the cold run cached
            shutil.rmtree(cache, ignore_errors=True)
            if snap.exists():
                shutil.copytree(snap, cache)
            measure(level, "rerun")
            if not args.no_rerun2:
                measure(level, "rerun2")
        else:
            measure(level, "rerun")                 # browser-use keeps no memory: every run is fresh


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", default="all", help="comma separated task names, or 'all': " + ", ".join(BY_NAME))
    ap.add_argument("--variants", default="ecogent,compile_only,nocache")
    ap.add_argument("--levels", default="0,1,2,3,4")
    ap.add_argument("--seeds", default="1,2,3", help="drift seeds: different site changes of the same size")
    ap.add_argument("--repeats", type=int, default=1,
                    help="independent repeats per seed (same pages, fresh agent): measures LLM randomness")
    ap.add_argument("--price", action="append", default=[], help="MODEL=IN,OUT[,CACHED] USD per 1M tokens")
    ap.add_argument("--out", default="bench/results/drift.csv")
    ap.add_argument("--work", default="", help="data folders for the cells (default: <out dir>/work)")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--headless", action="store_true", help="hide the browser (default: visible)")
    ap.add_argument("--interactive", action="store_true", help="wait for you when a run needs a person")
    ap.add_argument("--no-rerun2", action="store_true", help="skip the second rerun per level")
    ap.add_argument("--verbose", action="store_true", help="print the agent's log")
    ap.add_argument("--max-steps", type=int, default=60, help="step limit for external agents")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per external run")
    args = ap.parse_args()

    tasks = TASKS if args.tasks == "all" else [BY_NAME[n.strip()] for n in args.tasks.split(",")]
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    levels = [int(x) for x in args.levels.split(",")]
    seeds = [int(x) for x in args.seeds.split(",")]
    prices = parse_prices(args.price)
    base = Settings.load()
    if not base.main_llm.enabled:
        sys.exit("Configure the main LLM in the app's Settings first.")
    for v in variants:
        variant_settings(base, v)           # fail fast on a typo

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    args.work = args.work or str(out.parent / "work")
    manifest = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": git_commit(),
                "args": vars(args), "main_model": f"{base.main_llm.provider}:{base.main_llm.model}",
                "cheap_model": (f"{base.cheap_llm.provider}:{base.cheap_llm.model}" if base.cheap_llm.enabled else ""),
                "cheap_purposes": base.cheap_purposes, "tasks": [t.name for t in tasks], "levels": drift.LEVELS}
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    srv = LabServer(port=args.port)
    warned: set = set()
    new_file = not out.exists()
    try:
        with out.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            for task in tasks:
                for variant in variants:
                    for seed in seeds:
                        for rep in range(1, args.repeats + 1):
                            fn = run_external_cell if variant in EXTERNAL else run_cell
                            fn(task, variant, seed, rep, levels, args, base, srv, w, fh, prices, warned)
    finally:
        srv.close()
    print(f"\nRows appended to {out}; summarize with: python bench/summarize.py {out}")


if __name__ == "__main__":
    main()
