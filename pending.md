# Pending — where the work stopped (2026-11-13)

> To continue with Claude: open the repo and say "read pending.md and continue".
> Older notes (rules, what was built, open decisions): `Ecogent_Works_Doc/pending.md`.

---

## 1. Not committed yet (code changed today)

| File | Change | Why |
|---|---|---|
| `ecogent/browser.py` (`_new_manager`) | profile folder passed to the browser manager as an **absolute** path | A relative `--user-data-dir` made Brave fall back to your normal profile: benchmark pages opened as tabs in your own Brave, the debug port never opened (`ECONNREFUSED 127.0.0.1:9231`), every run failed. Checked: a separate Brave window now opens. |
| `bench/drift_bench.py` (`main`) | `--work` folder made absolute | Same bug from the benchmark side. |

The free fake-LLM checks (`fake_run`, `e2e_fake_llm.py`) were **not** re-run after this change (stopped on request).
Commit before the next benchmark session (the manifest records the git commit).

## 2. First head-to-head result (real LLM)

Task `papers_caching`, gpt-4o-mini via OpenRouter, price $0.15 / $0.60 / $0.075 per 1M (in / out / cached),
drift levels 0–4, seed 1, temperature **0.1** (not 0). Visible browser.

| | Ecogent | Stagehand | browser-use |
|---|---|---|---|
| Runs passing the oracle | **11 / 11** | 0 / 11 | 0 / 2 (both timed out at 420 s, then stopped) |
| Total LLM calls | **4** | 314 | not recorded |
| Total cost | **$0.0009** | $0.102 | unknown |
| Seconds per rerun | ~5 | 46–283 | >420 |
| Second rerun after drift | 0 calls at every level | 4–31 calls | — |

Ecogent detail: L0 cold 3 calls (plan, pick, analyze); L2 rerun 1 call (`analyze`, page text changed);
L3 / L4 reruns 0 calls — 1 broken element fixed by a **local pick** (no LLM), the report reused from the
analysis cache. All second reruns 0 calls = repairs written back.

Files: `bench/results/h2h.csv` (Ecogent + browser-use timeouts), `bench/results/h2h_stagehand.csv`,
`bench/results/work/` (per-run folders). `bench/results/` is git-ignored — back it up.

**This is one small task (12 steps, 3 element lookups), one seed: a first sign, not a paper result.**

## 3. Next steps (proposed — your decision)

1. **Check Stagehand's 0/11 is a fair failure** (free): read its output files in
   `bench/results/work/stagehand/papers_caching/s1r1/`. A baseline that never succeeds will be questioned;
   rule out a runner problem (e.g. how the final report is collected).
2. **Debug browser-use** (a few cents): run one cell with its log visible — `run_browser_use.py` output is
   currently discarded, so the cause of the 420 s timeouts is unknown. Candidates: vision ON (screenshots with
   gpt-4o-mini), timeout too short. Decide: add a vision-off variant?
3. Set **temperature 0** for both models, commit, then the **pilot** (4 tasks × 2 seeds) from
   `Ecogent_Works_Doc/benchmark_manual_testing.md` §2 — with `browser_use` and `stagehand` included.
4. Library note: `playwright_browser_manager` prints `✅`, which crashes on Windows when output goes to a file
   or pipe (cp1252). Run scripts with `PYTHONIOENCODING=utf-8` (used today), or fix it in the library.

## 4. Gaps before writing the IEEE paper (from today's review)

- No full benchmark data yet: pilot, full run, ablations, manual agents (Claude in Chrome / Perplexity /
  Antigravity), real-world study (4 weekly rounds — start round 1 early, it fixes the earliest submission date).
- Research statement (`Ecogent_Works_Doc/how_work.md` line 26) vs benchmark: **AWM-style baseline** not built;
  contribution (c) per-task-type reuse policies has **no experiment** isolating it; vector memory off,
  scraping sample auto-accepted, ablation switches in core — must be stated in the method; `how_work.md` still
  lists the tiny local LLM; N ≥ 5 per cell (`ecogent_vs_others.md` §9) vs 3 seeds in the run plan.
- Open decisions in `Ecogent_Works_Doc/pending.md` §4 still open.
- Reviewer risks: self-built benchmark (argue drift realism), `self_healing_test_site_plan.md` not built (level 1
  renames classes without CSS → pages look different, may be unfair to vision agents), one model family,
  prompt tuning on the test set (freeze prompts + record commit).
- Paper: venue + deadline + page limit + double-blind not chosen; no IEEEtran draft; new verified `.bib`
  (Agentic Compilation, Agentic Plan Caching, AgentRR, Stagehand, workflow-use, Similo, AutoCrawler, AWM);
  ladder pseudocode, cost model, threats to validity; release code + lab + CSVs; robots.txt / terms check for
  the 32 real cases; IEEE AI-text disclosure.

## 5. Commands used today

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python bench/drift_bench.py --tasks papers_caching --variants ecogent \
    --levels 0,1,2,3,4 --seeds 1 --price gpt-4o-mini=0.15,0.60,0.075 --out bench/results/h2h.csv \
    --max-steps 30 --timeout 420
PYTHONIOENCODING=utf-8 .venv/Scripts/python bench/drift_bench.py --tasks papers_caching --variants stagehand \
    --levels 0,1,2,3,4 --seeds 1 --price gpt-4o-mini=0.15,0.60,0.075 --out bench/results/h2h_stagehand.csv \
    --max-steps 30 --timeout 420
```
