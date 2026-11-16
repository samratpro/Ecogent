# Benchmark: Automatic vs Manual Work

> Which parts of the benchmark run by themselves (the app / scripts) and which parts you do yourself.
> Step-by-step commands for the manual parts: `benchmark_manual_testing.md`.
> Created 2026-11-15.

---

## 1. At a glance

| Part | Automatic (app / scripts) | Manual (you) |
|---|---|---|
| Free checks (lab self-test, fake-LLM run) | ✅ one click in **Benchmark → Run setup** | — |
| Test shop (port 3010): start / stop, scenarios, look + flow checks | ✅ sidebar → **Test Lab** | pick scenarios for manual tests; freeze the shop (git tag) before the first agent run |
| Shop benchmark: 9 held-out tasks, 10 change types, oracles on live ground truth | ✅ `drift_bench --site shop`, or Run setup → Site: shop | never tune Ecogent on these tasks |
| **Paper run**: checklist reviewers check, recorded with the results, paper report | ✅ **Benchmark → Paper run** | commit + tag, temperature 0, price date, write and commit `bench/preregistration.md` |
| Settings: models, API keys, temperature 0, prices with date | — | ✅ |
| Commit code before a session | — | ✅ |
| Lab benchmark runs: Ecogent, `nocache`, `compile_only`, `no_cheap`, ablations | ✅ Run now or on a schedule | watch the first runs |
| External baselines: Stagehand, browser-use | ✅ same runner, same oracles, same prices | install once; check that their failures are fair |
| Scoring (success / precision / recall) | ✅ oracles against ground truth | — |
| Tokens, LLM calls, USD, seconds per run | ✅ written to the CSV + manifest (git commit, models) | — |
| Tables, paired tests, break-even, figures | ✅ **Benchmark → Results** (Markdown summary, Figures) | read them and decide |
| When the automatic runs happen | ✅ schedule: off / once / daily / weekly | choose it |
| Manual agents: Claude in Chrome, Perplexity Comet, Antigravity | — | ✅ `python -m bench.lab.serve` (success + time only) |
| Real-world study: 32 real cases, weekly rounds | — | ✅ `python bench/real_log.py` |
| Notes for the paper (prices, machine, anything unusual) | — | ✅ `bench/results/NOTES.md` |
| Back up `bench/results/` (git-ignored) | — | ✅ |
| Decisions: which baselines, public benchmark subset, second model family, AWM | — | ✅ |
| Writing the paper | — | ✅ |

---

## 2. Automatic part

### 2.1 What runs
The app starts `bench/drift_bench.py` as a separate process. Every number in the window comes from the same
CSV the paper uses, and the same command works in a terminal.

For every task × system × seed (one "cell"):
1. **cold** run at drift level 0: solves the task from the prompt
2. for each drift level: a **rerun** (plan from the cold run restored, site changed) and a **rerun2**
   (run again: 0 calls means the repair was saved)
3. each run is scored by the task's oracle, and its tokens, cached tokens, calls by purpose, USD and
   seconds become one CSV row

`nocache` and `browser_use` keep no memory, so they get one fresh run per level and no rerun2.

### 2.2 The Benchmark window (sidebar → **Benchmark**)

| Tab | What it does |
|---|---|
| **Results** | Tick one or more CSVs from `bench/results/`. Shows a **By system** table (passed, LLM calls, total cost, cold run, mean rerun, ×Ecogent, seconds, rerun2 at 0 calls, timeouts), a **By drift level** table (passed / cost / calls per level) and the individual runs. **Markdown summary** runs `bench/summarize.py` (mean ± sd, 95% CI, paired tests, cost of ownership); **Figures** runs `bench/plot.py` (SVG). |
| **Run setup** | Tasks (24 lab tasks), systems, drift levels, seeds, repeats, prices, result name, step limit / timeout for external agents, headless, skip rerun2. Shows the number of cells and runs and the exact command. **Run now**, **Stop**, **Save settings**, and the two free checks. |
| **Output** | Live output of the running benchmark or check. |
| **Schedule** | When the automatic benchmark runs (see 2.3). |

A run that times out without reporting usage is shown as unknown cost (`-`), not $0.

### 2.2b Paper run (Benchmark → Paper run)
Pick an experiment (main comparison on the lab, main comparison on the test shop, ablations, or a pilot). The
checklist must be green before **Start paper run** is enabled:

| Check | Why reviewers care |
|---|---|
| Code committed + git tag | Results belong to a known, frozen code version (no tuning after seeing results) |
| Temperature 0 | Less randomness between runs |
| Prices for every model + price date | Dollar figures must name model, price and date |
| ≥ 5 seeds | Mean ± spread, confidence intervals, paired tests |
| Required baselines (ecogent, nocache, compile_only, no_cheap if a cheap model is used, an external agent) | No strawman comparison; savings attributed to reuse and repair, not to the cheap model |
| External agents installed | Their runs must not fail for setup reasons |
| `bench/preregistration.md` committed | Hypotheses written before the results, including unfavourable ones |
| Free checks passed at this commit (lab self-test, fake run; for the shop also task self-test, look, flow) | The measuring tools work on exactly this code |
| New result file | Rows from different code versions never mix |

**Start anyway** is possible, but the run is then marked NOT paper-ready, and every failed check is listed as a
deviation in the report. The checklist, environment (OS, Python, Node, settings without API keys) and price date
go into `<name>.meta.json` and the manifest. **Make paper report** writes `<name>_paper_report.md`: protocol,
deviations, statistics tables and figures.

### 2.3 Schedule: when the automatic test runs
- Modes: **off** (only when you press Run now), **once** (date + time), **daily** (time), **weekly** (day + time).
- It uses the tasks and systems **saved** in Run setup (press **Save settings** after changing them).
- The **app must be open**. If it was closed at the due time, the run starts the next time you open the app.
- **Wait while Ecogent is busy** (on by default): a due run waits until the current Ecogent task has finished.
- A due run that cannot start (e.g. no API key) is skipped and logged. A once-only schedule then ends.
- Saved in `ecogent_data/bench_config.json`.
- Scheduled runs are **real, paid API runs**. The browser is visible unless Headless is ticked. The lab sites
  have no captchas, so nobody needs to be at the computer.

### 2.4 Rules the app follows
- The benchmark browser uses its own debug port (the app's port + 40), so a browser the app has open is never taken over.
- Only one benchmark or check runs at a time. Closing the window does not stop it; **Stop** does.
  Rows already written are kept.
- Rows are **appended** to `bench/results/<result name>.csv`. Use a new result name for a new experiment.

---

## 3. Manual part (you)

### 3.1 Before every paid session
1. Settings: main (+ cheap) model, **temperature 0**, and today's prices noted in `NOTES.md` with the date.
2. `git commit`: the manifest records the commit, so results match a known code version.
3. Run the free checks (Benchmark → Run setup): `LAB OK` and `FAKE RUN OK`.
4. Don't run Ecogent tasks in the app during a benchmark: they slow the machine down, which changes the timing numbers.

### 3.2 During and after runs
- Watch the browser for the first runs of a new setup, and don't click in it.
- **Check that baseline failures are fair** before trusting a comparison. Example: Stagehand passed 0 of 11
  runs on 2026-11-13. Read its `result.json` / `final_answer.*` in `bench/results/work/stagehand/...` to
  confirm it is the agent failing and not our runner.
- Read Results / the Markdown summary and decide the next step (pilot → full run → ablations).
- Note anything unusual (crash, rate limit, odd row) with the row's time in `NOTES.md`.
- Back up `bench/results/` (git-ignored).

### 3.3 Manual agents (success and time only, never tokens / dollars)
Claude in Chrome, Perplexity Comet, Antigravity: `python -m bench.lab.serve --system <name-version> --level 0 --seed 1`.
Same tasks, same drift levels, the oracle scores the result. Rules: paste the prompt exactly, one attempt,
fresh chat, don't help (write down any answer you give). At least levels 0 and 3. Details: `benchmark_manual_testing.md` §5.

### 3.4 Real-world study
32 cases on public practice sites, 4 weekly rounds, `python bench/real_log.py --system <name> --round <n>`.
Check each site's terms / robots.txt before round 1. Details: `benchmark_manual_testing.md` §5b.

### 3.5 Decisions only you make
- Which baselines go into the paper (smallest set reviewers are likely to accept: Stagehand + browser-use +
  `nocache` + `compile_only`).
- browser-use with vision off as an extra variant?
- Public benchmark subset (TimeWarp / StressWeb)? Second model family?
- AWM-style baseline: build it, or remove it from the research statement?
- Venue, deadline, and the paper itself.

---

## 4. Where things are

| What | Where |
|---|---|
| Results (CSV + manifest) | `bench/results/<name>.csv`, `<name>.manifest.json` |
| Per-run folders (plans, outputs, external agents' result.json) | `bench/results/work/<system>/<task>/s<seed>r<repeat>/` |
| Summaries / figures from the window | `bench/results/<name>_summary.md`, `bench/results/figures/<name>/` |
| Benchmark settings + schedule | `ecogent_data/bench_config.json` |
| Code | `ecogent/bench_runner.py` (logic), `ecogent/gui/benchmark.py` (window), `bench/drift_bench.py` (runner) |
