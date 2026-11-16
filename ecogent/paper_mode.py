"""
Paper mode for the benchmark: the protocol reviewers check, enforced before a run and recorded with it.

- PRESETS          the experiments of the paper (main comparison on the lab and on the test shop, ablations, pilot)
- readiness()      the checklist: frozen code (committed + git tag), temperature 0, prices with a date, N >= 5 seeds,
                   all baselines, baselines installed, pre-registration committed, free checks passed at this commit,
                   a new result file
- write_meta()     what gets stored next to the results (checklist, environment, settings without API keys)
- paper_report()   one markdown file per experiment: protocol, deviations, the statistics tables, the figures

Nothing here changes how a run is measured: the app still starts bench/drift_bench.py with arguments.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from . import bench_runner as br
from .config import Settings
from .storage import read_json, write_json

REPO = br.REPO
PREREG = REPO / "bench" / "preregistration.md"
MIN_SEEDS = 5
MAIN_VARIANTS = ["ecogent", "nocache", "compile_only", "no_cheap", "stagehand", "browser_use"]
ABLATION_VARIANTS = ["ecogent", "no_identity", "no_alternates", "no_refind", "no_obvious", "no_graded", "no_cheap"]

PRESETS = {
    "main_lab": {"title": "Main comparison: lab sites", "paper": True, "site": "lab", "tasks": "all",
                 "variants": MAIN_VARIANTS, "levels": "0,1,2,3,4", "seeds": "1,2,3,4,5",
                 "about": "24 lab tasks x drift levels 0-4 (cumulative) x 5 seeds, Ecogent vs every baseline."},
    "main_shop": {"title": "Main comparison: test shop (held-out)", "paper": True, "site": "shop", "tasks": "all",
                  "variants": MAIN_VARIANTS, "levels": "0,1,2,3,4,5,6,7,8,9", "seeds": "1,2,3,4,5",
                  "about": "9 held-out shop tasks x 10 real-world change types x 5 seeds. Ecogent was never tuned on these."},
    "ablations": {"title": "Ablation study", "paper": True, "site": "lab", "tasks": "all",
                  "variants": ABLATION_VARIANTS, "levels": "0,1,2,3,4", "seeds": "1,2,3,4,5",
                  "about": "Ecogent with one component of the element-lookup ladder disabled at a time."},
    "pilot": {"title": "Pilot study (exploratory)", "paper": False, "site": "lab",
              "tasks": ["shop_baby_under_30", "papers_caching", "jobs_python", "crm_add_deal"],
              "variants": ["ecogent", "nocache", "compile_only", "stagehand", "browser_use"], "levels": "0,1,2,3,4", "seeds": "1,2",
              "about": "4 tasks x 2 seeds: estimates run time and cost and verifies that every system runs."},
    "pilot_shop": {"title": "Pilot study: test shop (exploratory)", "paper": False, "site": "shop",
                   "tasks": ["nw_books_under_20", "nw_kitchen_price_range", "nw_cart_setup"],
                   "variants": ["ecogent", "nocache", "compile_only", "no_cheap", "stagehand", "browser_use"],
                   "levels": "0,2,5,6,8", "seeds": "1",
                   "about": "One scraping, analysis and automation task x baseline, markup refactor, redesign, copy change "
                            "and data change x 1 seed: checks task difficulty (no floor / ceiling) and that every system "
                            "runs. Not reported as results; do not change Ecogent after seeing it (the shop is held out)."},
}

# Free checks a paper run needs, per site (label -> how its success is recognised in the output)
CHECKS_FOR_SITE = {"lab": ["Lab integrity test", "Lab visual invariance test", "Pipeline test (mock LLM)"],
                   "shop": ["Lab integrity test", "Pipeline test (mock LLM)", "Shop oracle test", "Shop visual invariance test", "Shop task-completion test"]}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    required: bool = True


# ----------------------------------------------------------------------------- helpers
def _git(*args: str, strip: bool = True) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=15)
        return (r.stdout.strip() if strip else r.stdout) if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def commit() -> str:
    return _git("rev-parse", "HEAD")


def tag() -> str:
    return _git("describe", "--tags", "--exact-match", "HEAD")


def dirty_files() -> list[str]:
    out = _git("status", "--porcelain", "--", "ecogent", "bench", "test_shop", "pyproject.toml", "requirements.txt", strip=False)
    files = [l[3:].strip().strip('"') for l in out.splitlines() if len(l) > 3]   # "XY path": never strip the XY columns first
    return [f for f in files if not f.startswith("bench/results") and "__pycache__" not in f]


def preset_tasks(preset: dict) -> list[str]:
    return br.task_names(preset["site"]) if preset["tasks"] == "all" else list(preset["tasks"])


def preset_config(key: str, base: dict) -> dict:
    p = PRESETS[key]
    cfg = dict(base)
    cfg.update(site=p["site"], tasks=preset_tasks(p), variants=list(p["variants"]), levels=p["levels"], seeds=p["seeds"],
               repeats=1, headless=False, no_rerun2=False,
               out_name=f"{'paper' if p['paper'] else 'pilot'}_{key}_{date.today():%Y%m%d}")
    return cfg


def checks_file(settings: Settings) -> Path:
    return settings.home_path / "bench_checks.json"


def record_check(settings: Settings, label: str, ok: bool) -> None:
    """Remember that a free check passed / failed at the current commit (and whether the tree was clean)."""
    data = read_json(checks_file(settings), {})
    data[label] = {"ok": ok, "commit": commit(), "clean": not dirty_files(), "time": datetime.now().isoformat(timespec="seconds")}
    write_json(checks_file(settings), data)


def _price_models(prices: str) -> set[str]:
    return {p.split("=", 1)[0].strip().split(":", 1)[-1] for p in str(prices).split(";") if "=" in p}


# ----------------------------------------------------------------------------- readiness
def readiness(settings: Settings, cfg: dict, paper: bool = True) -> list[Check]:
    out: list[Check] = []
    dirty = dirty_files()
    out.append(Check("Clean working tree", not dirty,
                     "clean" if not dirty else f"{len(dirty)} uncommitted file(s): {', '.join(dirty[:4])}{' ...' if len(dirty) > 4 else ''}",
                     "Commit all changes. Results must map to a recorded code version."))
    t = tag()
    out.append(Check("Tagged release", bool(t), f"tag {t}" if t else f"commit {commit()[:10]} has no tag",
                     "Tag the commit (e.g. git tag v1.0). Do not change prompts after observing results."))
    llms = [("main", settings.main_llm)] + ([("cheap", settings.cheap_llm)] if settings.cheap_llm.enabled else [])
    temps = {n: c.temperature for n, c in llms}
    out.append(Check("Deterministic decoding (temperature 0)", all(v == 0 for v in temps.values()),
                     ", ".join(f"{n} {v:g}" for n, v in temps.items()),
                     "Settings > Main LLM and Cheap model: set Temperature to 0."))
    have = _price_models(cfg.get("prices", ""))
    need = {c.model for _, c in llms}
    missing = sorted(m for m in need if m not in have)
    out.append(Check("Pricing for all models", not missing, "complete" if not missing else f"missing: {', '.join(missing)}",
                     "Configuration > Pricing: MODEL=IN,OUT,CACHED (USD per 1M tokens) for each model."))
    pd = str(cfg.get("price_date", ""))
    pd_ok = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", pd))
    out.append(Check("Pricing date", pd_ok, pd or "not set",
                     "Enter the date the prices were taken from the provider pricing pages (YYYY-MM-DD)."))
    try:
        n_seeds = len([s for s in str(cfg.get("seeds", "")).split(",") if s.strip()])
    except ValueError:
        n_seeds = 0
    out.append(Check(f"Sample size (>= {MIN_SEEDS} seeds)", n_seeds >= MIN_SEEDS, f"{n_seeds} seed(s)",
                     f"Use {MIN_SEEDS} or more seeds (e.g. 1,2,3,4,5) to report means, confidence intervals and tests."))
    variants = set(cfg.get("variants") or [])
    is_ablation = any(v in variants for v in ("no_identity", "no_alternates", "no_refind", "no_obvious", "no_graded"))
    want = {"ecogent"} if is_ablation else {"ecogent", "nocache", "compile_only"}
    if settings.cheap_llm.enabled:
        want.add("no_cheap")
    lacking = sorted(want - variants)
    ext_ok = is_ablation or bool(variants & {"stagehand", "browser_use", "browser_use_novision"})
    out.append(Check("Baseline coverage", not lacking and ext_ok,
                     ("complete" if not lacking else f"missing: {', '.join(lacking)}") +
                     ("" if ext_ok else "; no external agent (stagehand / browser_use)"),
                     "Main comparison: ecogent, nocache (no reuse), compile_only (no repair), no_cheap (if a cheap model "
                     "is used) and at least one external agent."))
    inst = []
    if variants & {"browser_use", "browser_use_novision"} and not (REPO / ".venv-baselines" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")).exists():
        inst.append("browser-use (.venv-baselines)")
    if "stagehand" in variants and not (REPO / "bench" / "baselines" / "stagehand" / "node_modules").exists():
        inst.append("Stagehand (npm install in bench/baselines/stagehand)")
    out.append(Check("Baseline installation", not inst, "ok" if not inst else "missing: " + ", ".join(inst),
                     "Install the missing baseline (see bench/baselines)."))
    prereg_dirty = any(f.endswith("preregistration.md") for f in _git("status", "--porcelain", "--", "bench").splitlines())
    prereg_ok = PREREG.exists() and not prereg_dirty and bool(_git("ls-files", str(PREREG.relative_to(REPO))))
    out.append(Check("Pre-registered hypotheses", prereg_ok,
                     "bench/preregistration.md committed" if prereg_ok else
                     ("bench/preregistration.md has uncommitted edits" if PREREG.exists() else "bench/preregistration.md missing"),
                     "Create it (Open pre-registration), state all hypotheses including unfavourable ones, and commit it before the run."))
    done = read_json(checks_file(settings), {})
    c = commit()
    for label in CHECKS_FOR_SITE.get(cfg.get("site", "lab"), []):
        r = done.get(label) or {}
        ok = bool(r.get("ok")) and r.get("commit") == c and r.get("clean", False)
        detail = ("passed at this commit" if ok else "not run at this commit" if r.get("commit") != c or not r
                  else "failed" if not r.get("ok") else "run with uncommitted changes")
        out.append(Check(f"Validation: {label}", ok, detail,
                         "Run it after committing: Configuration > Validation, or Test Lab > Validation."))
    exists = br.out_csv(cfg).exists()
    out.append(Check("Unique output file", not exists, br.out_csv(cfg).name + (" already exists" if exists else ""),
                     "Use a new result name so that runs from different code versions are never mixed."))
    tasks_all = br.task_names(cfg.get("site", "lab"))
    sel = [t for t in cfg.get("tasks") or [] if t in tasks_all]
    same = settings.cheap_llm.enabled and settings.cheap_llm.model == settings.main_llm.model
    out.append(Check("Distinct main and cheap models", not same,
                     f"main {settings.main_llm.model}" + (f", cheap {settings.cheap_llm.model}" if settings.cheap_llm.enabled else ", no cheap model"),
                     "With the same model for both, routing saves nothing and no_cheap equals ecogent. Use a stronger "
                     "main model, or disable the cheap model and report that.", required=False))
    out.append(Check("Complete task suite", len(sel) == len(tasks_all), f"{len(sel)} of {len(tasks_all)} tasks",
                     "A subset must be justified in the paper.", required=False))
    if not paper:
        for ch in out:
            ch.required = False
    return out


def ready(checks: list[Check]) -> bool:
    return all(c.ok for c in checks if c.required)


# ----------------------------------------------------------------------------- meta + report
def _version(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return ""


def environment(settings: Settings) -> dict:
    s = json.loads(json.dumps(asdict(settings)))
    for k in ("main_llm", "cheap_llm"):
        if isinstance(s.get(k), dict):
            s[k].pop("api_key", None)
    keep = ("main_llm", "cheap_llm", "cheap_purposes", "max_heal_attempts", "max_heals_per_run", "max_rescue_turns",
            "max_rescues_per_run", "max_run_tokens", "analysis_budget_chars", "analysis_direct_chars", "max_page_chars",
            "scrape_sample_size", "page_wait_s", "bot_check_wait_s", "browser_path")
    return {"os": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
            "python": sys.version.split()[0], "node": _version(["node", "--version"]) if shutil.which("node") else "",
            "git_commit": commit(), "git_tag": tag(), "settings": {k: s.get(k) for k in keep if k in s}}


def write_meta(settings: Settings, cfg: dict, preset: str, checks: list[Check]) -> Path:
    p = br.RESULTS / f"{cfg['out_name']}.meta.json"
    br.RESULTS.mkdir(parents=True, exist_ok=True)
    meta = {"preset": preset, "preset_title": PRESETS.get(preset, {}).get("title", "custom"),
            "paper_ready": ready(checks), "price_date": cfg.get("price_date", ""), "prices": cfg.get("prices", ""),
            "checklist": [asdict(c) for c in checks], "environment": environment(settings),
            "written": datetime.now().isoformat(timespec="seconds")}
    p.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return p


PREREG_TEMPLATE = """# Pre-registration: Ecogent benchmark

> Write this BEFORE the paid runs and commit it. Do not edit it after seeing results; add a dated
> "Deviations" section at the end instead. Reviewers will compare the paper with this file.

Date: {today}
Code version (git tag): <tag>

## Research question
<one or two sentences, in your words>

## Systems compared
ecogent, nocache (no reuse), compile_only (no repair), no_cheap (main model only), stagehand, browser_use
<manual agents, if any: success and time only>

## Tasks and sites
- Lab: 24 tasks, drift levels 0-4 (cumulative)
- Test shop (held-out, never used for tuning): 9 tasks, levels 0-9 (one real-world change each)

## Primary outcomes
- Cost per rerun (USD) by drift level / change type
- Success rate (oracle) by drift level / change type

## Hypotheses (including the ones where Ecogent is expected to do worse)
- H1 <...>
- H2 <...>
- Unfavourable: <e.g. wording changes, full redesign, new class names every load, new data>

## Statistics
- N = 5 seeds per cell (task x system x level); mean ± sd and 95% bootstrap CI
- Paired tests vs ecogent on the same (task, seed, level): Wilcoxon (cost), exact binomial (success); alpha 0.05
- Every run is reported; no run is removed after seeing it (except documented infrastructure failures, re-run)

## Exclusions and re-runs
<what counts as an infrastructure failure (provider outage, crash) and how it is re-run>

## Deviations (added later, dated)
"""


def create_prereg() -> Path:
    if not PREREG.exists():
        PREREG.write_text(PREREG_TEMPLATE.format(today=date.today().isoformat()), encoding="utf-8")
    return PREREG


def paper_report(csv_path: Path) -> Path:
    """<name>_paper_report.md: protocol + deviations from the manifest/meta, then summarize.py's tables, then figures."""
    name = csv_path.stem
    manifest = read_json(csv_path.with_suffix(".manifest.json"), {})
    meta = read_json(csv_path.with_name(f"{name}.meta.json"), {})
    env = meta.get("environment", {})
    fig_dir = br.RESULTS / "figures" / name
    env_vars = {"PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(REPO)}
    import os
    env_full = {**os.environ, **env_vars}
    summ = subprocess.run([sys.executable, str(br.BENCH / "summarize.py"), str(csv_path), "--by-task"], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env_full)
    subprocess.run([sys.executable, str(br.BENCH / "plot.py"), str(csv_path), "--out", str(fig_dir)], cwd=REPO,
                   capture_output=True, text=True, env=env_full)
    rows = br.read_rows([csv_path])
    failed = [c for c in meta.get("checklist", []) if c.get("required") and not c.get("ok")]
    args = manifest.get("args", {})
    lines = [f"# Benchmark report: {name}", "",
             f"**{'Protocol compliant' if meta.get('paper_ready') else 'Protocol deviations'}** - {meta.get('preset_title', 'custom run')}", "",
             "## Protocol", "",
             f"- Site: {manifest.get('site', 'lab')}; levels: {manifest.get('levels')}",
             f"- Tasks ({len(manifest.get('tasks', []))}): {', '.join(manifest.get('tasks', []))}",
             f"- Systems: {args.get('variants', '')}",
             f"- Seeds: {args.get('seeds', '')}; repeats: {args.get('repeats', 1)}; rerun2: {not args.get('no_rerun2')}",
             f"- Runs recorded: {len(rows)}",
             f"- Main model: {manifest.get('main_model')}; cheap model: " +
             (f"{manifest['cheap_model']} (jobs: {', '.join(manifest.get('cheap_purposes') or [])})" if manifest.get("cheap_model") else "none"),
             f"- Prices (USD / 1M tokens, in/out/cached): {meta.get('prices') or args.get('price')}; read on {meta.get('price_date') or '?'}",
             f"- Temperature: main {env.get('settings', {}).get('main_llm', {}).get('temperature', '?')}"
             + (f", cheap {env.get('settings', {}).get('cheap_llm', {}).get('temperature')}" if manifest.get('cheap_model') else ""),
             f"- Code: commit {manifest.get('git_commit', '')[:12]}, tag {env.get('git_tag') or 'none'}; started {manifest.get('started')}",
             f"- Machine: {env.get('os', '?')}, Python {env.get('python', '?')}, Node {env.get('node', '?')}",
             "- External agents (stagehand, browser_use) use the same main model, prompts with one disclosed addition, "
             "the same oracles and prices; general agents tested by hand are reported separately (success and time only).",
             "", "## Deviations from protocol", ""]
    if not meta:
        lines += ["- No reproducibility checklist was recorded (run not started from Benchmark > Experiment): "
                  "treat this run as exploratory, not as a paper result."]
    else:
        lines += [f"- {c['name']}: {c['detail']}" for c in failed] or ["- none"]
    lines += ["", summ.stdout.strip() if summ.returncode == 0 else f"(summary failed: {summ.stderr.strip()[-300:]})",
              "", "## Figures", ""]
    figs = sorted(fig_dir.glob("*.svg")) if fig_dir.exists() else []
    lines += [f"- figures/{name}/{f.name}" for f in figs] or ["- (no figures)"]
    out = br.RESULTS / f"{name}_paper_report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
