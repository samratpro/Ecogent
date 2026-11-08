# Pending — where the work stopped (2026-11-09)

> Read this first when you continue. To continue with Claude: open the repo and say
> "read Ecogent_Works_Doc/pending.md and continue".
> Not committed yet: the Stagehand fix + drift_bench fix + skill note from 2026-11-08 (see `git status`).

---

## 1. Rules agreed

- **You own the research.** Claude does only what you ask; it proposes, you decide (saved in Claude's memory).
- Ecogent is **browser-only**; **no local / tiny LLM**; two API models: **main** + optional **cheap** (small jobs).
- The old paper drafts in `research/` are **invalid**; the paper will be written **after the benchmark**.
- Target: an IEEE-quality paper. Research statement = `how_work.md` line 26 (benchmark of repeated tasks with
  deliberate site changes, against browser-use, a no-cache baseline and an AWM-style baseline).
- Real-LLM tests: visible browser, a human solves captchas.

## 2. Done (all tested with fake LLM / self-tests)

| Area | What | Files |
|---|---|---|
| Ecogent fixes | captcha 403/429 → pause (no LLM), no reload after Continue, survives Google redirects; persistent `default` profile; page wait + bot-check wait; "browser closed" message; compact Browser section; sharp text; selectable chat text + Copy | `ecogent/executor.py`, `browser.py`, `config.py`, `core.py`, `gui/*` |
| Models | tiny local LLM removed; `cheap_llm` / `cheap_purposes`; Ollama removed | `config.py`, `llm.py`, `gui/dialogs.py`, `README.md` |
| Docs | comparison with other systems; manual test guide | `ecogent_vs_others.md`, `benchmark_manual_testing.md` |
| Lab benchmark | 24 tasks (8 scraping / 7 analysis / 9 automation), 4 local sites, drift levels 0–4, oracles | `bench/lab/*` — `python -m bench.lab.selftest` → `LAB OK` |
| Runner | variants `ecogent`, `nocache`, `compile_only`, `no_cheap`, ablations, `--repeats` | `bench/drift_bench.py` — `python -m bench.lab.fake_run <dir>` → `FAKE RUN OK` |
| Stats / figures | CIs, paired tests, cost of ownership + break-even; 4 SVG figures | `bench/summarize.py`, `bench/plot.py` |
| Real-world study | 32 real cases on practice sites + weekly logging console | `bench/real_cases.json`, `bench/real_log.py` |
| Manual agents | console for Claude in Chrome / Perplexity / Antigravity on the lab sites | `bench/lab/serve.py` |

## 3. External baselines

| Baseline | Installed | Runner | Status |
|---|---|---|---|
| **browser-use** 0.13.14 | `.venv-baselines/` (git-ignored) | `bench/baselines/run_browser_use.py`, variant `browser_use` | Works. Default = vision ON (screenshots → huge tokens with gpt-4o-mini). **Re-run its earlier numbers** — the scoring bug below dropped final-text answers. |
| **Stagehand** 3.7.3 + zod 4.6.6 | `bench/baselines/stagehand/node_modules` (npm) | `bench/baselines/stagehand/run_stagehand.mjs`, variant `stagehand` | **Fixed 2026-11-08, usable.** Test papers_caching (gpt-4o-mini/OpenRouter): cold 36 calls $0.0129; L2 rerun 6 calls $0.0019; L2 rerun2 6 calls $0.0015; L0 cache replay 0 calls. Oracle 0/3 = fair fail (right titles, invented findings, never extracted page text). |

Fixes made on 2026-11-08:
1. Stagehand `act` got HTTP 400 from OpenAI strict mode (schema object without `additionalProperties: false`).
   The runner middleware now closes every object schema; Stagehand logic unchanged.
2. Stagehand's final message is only a summary → the report is requested via the agent `output` schema
   (`experimental: true`; checked: in 3.7.3 local mode it changes nothing else).
3. `drift_bench.external_output` bug: final answers of all external agents were discarded unless a file was written.

## 4. Decisions waiting for you
- **browser-use with vision off** as an extra variant (fairer with gpt-4o-mini)?
- **AWM-style baseline** (named in how_work.md) — not built yet.
- More external agents (e.g. Skyvern, Notte, LaVague) — only if you want them.
- Items that may go against your plan (nothing changed yet):
  1. Claude called contribution (c) "per-task-type reuse policies" weak — your plan lists it as a contribution.
  2. Benchmark runs set `use_vector_memory = False` (ChromaDB off) — your design includes it.
  3. Benchmark auto-accepts the scraping sample (your flow has user confirmation).
  4. Claim wording ("cost scales with site drift") is in the skill / memory — rewrite in your words?
  5. Ablation switches added to Ecogent core code (off by default).

## 5. Your manual work (from `benchmark_manual_testing.md`)
1. Settings: main + cheap model, prices with date, temperature 0; commit code.
2. Free checks: `python -m bench.lab.selftest`, `python -m bench.lab.fake_run bench/results/fake`.
3. Pilot run (4 tasks), read `pilot_summary.md`.
4. Full run in batches (incl. `browser_use`, `stagehand`), ablations, figures.
5. Real-world study: 32 cases, weekly rounds (`bench/real_log.py`).
6. Hand-test Claude / Perplexity / Antigravity with `bench/lab/serve.py`.
7. Later: portable .exe (PyInstaller) — after code is final; does not replace releasing source + lab.

## 6. Useful commands
```bash
python -m bench.lab.selftest                                   # LAB OK
python -m bench.lab.fake_run bench/results/fake                 # FAKE RUN OK
python bench/drift_bench.py --tasks papers_caching --variants browser_use,stagehand --levels 2 --seeds 1 \
    --price gpt-4o-mini=0.15,0.60,0.075 --out bench/results/test.csv --max-steps 30 --timeout 420
python bench/summarize.py bench/results/test.csv
python bench/plot.py bench/results/test.csv --out bench/results/figures
```
Agent tests: `.venv/Scripts/python .claude/skills/ecogent/scripts/e2e_fake_llm.py .claude/skills/ecogent/site <dir>/home` → `ALL OK`.
