# Pending — where the work stopped (2026-11-08)

> Read this first when you continue. Nothing below is committed to git yet (`git status` shows all of it).
> To continue with Claude: open the repo and say "read Ecogent_Works_Doc/pending.md and continue".

---

## 1. Rules agreed in this session

- **You own the research.** Claude does only what you ask; it proposes, you decide (saved in Claude's memory).
- Ecogent is **browser-only**; **no local / tiny LLM**; two API models: **main** + optional **cheap** (small jobs).
- The old paper drafts in `research/` are **invalid**; the paper will be written **after the benchmark**.
- Target: an IEEE-quality paper. Research statement = `how_work.md` line 26 (benchmark of repeated tasks with
  deliberate site changes, against browser-use, a no-cache baseline and an AWM-style baseline).
- Real-LLM tests: visible browser, a human solves captchas.

## 2. Done (all tested with fake LLM / self-tests)

| Area | What | Files |
|---|---|---|
| Ecogent fixes | captcha 403/429 → pause (no LLM), no reload after Continue, survives Google redirects; persistent `default` profile; page wait + bot-check wait (dialog + Settings); "browser closed" message; compact Browser section; sharp text (DPI aware); selectable chat text + Copy button | `ecogent/executor.py`, `browser.py`, `config.py`, `core.py`, `gui/*` |
| Models | tiny local LLM removed; `cheap_llm` / `cheap_purposes` (old keys migrated); Ollama removed | `config.py`, `llm.py`, `gui/dialogs.py`, `README.md` |
| Docs | comparison with other systems; manual test guide | `Ecogent_Works_Doc/ecogent_vs_others.md`, `benchmark_manual_testing.md` |
| Lab benchmark | 24 tasks (8 scraping / 7 analysis / 9 automation), 4 local sites (shop, papers, jobs, CRM with login/popup/table/load-more/wizard), drift levels 0–4, oracles | `bench/lab/*` — check: `python -m bench.lab.selftest` → `LAB OK` |
| Runner | variants `ecogent`, `nocache`, `compile_only`, `no_cheap`, ablations, `--repeats` | `bench/drift_bench.py` — check: `python -m bench.lab.fake_run <dir>` → `FAKE RUN OK` |
| Stats / figures | CIs, paired tests, cost of ownership + break-even; 4 SVG figures | `bench/summarize.py`, `bench/plot.py` |
| Real-world study | 32 real cases on practice sites + weekly logging console | `bench/real_cases.json`, `bench/real_log.py` |
| Manual agents | console for Claude in Chrome / Perplexity / Antigravity on the lab sites | `bench/lab/serve.py` |

## 3. In progress: external baselines (you approved installing them)

| Baseline | Installed | Runner | Status |
|---|---|---|---|
| **browser-use** 0.13.14 | `.venv-baselines/` (separate venv, git-ignored) | `bench/baselines/run_browser_use.py`, variant `browser_use` | **Works.** Test (papers_caching, L0, gpt-4o-mini via OpenRouter): cold run 30 calls, 2.18M input tokens, ≈$0.31, found 1/3 facts, hit the 30-step test limit; its rerun timed out (420 s). Default settings = vision ON (screenshots → huge token counts with gpt-4o-mini). |
| **Stagehand** 3.7.3 (TypeScript; v4 has no whole-task agent) | `bench/baselines/stagehand/node_modules` (npm) | `bench/baselines/stagehand/run_stagehand.mjs`, variant `stagehand` | **Runs and counts tokens, but every `act` (typing / clicking) fails** → task fails, cache stays empty. **Not yet a fair baseline — do not use its numbers.** |

### Next step for Stagehand (diagnosis was in progress)
The log (`stagehand.log` in each run folder, now written with `verbose` from the config) shows the agent
calling `act("type 'web agent caching' into the Search papers textbox")` repeatedly, but not why it fails.
Likely causes to test, one at a time:
1. **OpenRouter + `openaiEndpointFormat: "chat"`** — `act` needs structured (JSON-schema) output; test with a
   direct OpenAI key (provider `openai`) or another model.
2. **Brave** as the browser — test with Chrome or Playwright's Chromium (`executable` in the config).
3. Write a 10-line script that only does `stagehand.act("type hello into the search box")` on
   `http://127.0.0.1:8790/papers/` (start the lab with `python -m bench.lab.serve --system test`) and print
   the returned `ActResult` — it contains the real error.
Diagnosis setup used: config `scratchpad/ext/diag/cfg.json` style — see `run_external_cell` in
`bench/drift_bench.py` for the config fields.

### Decisions waiting for you
- **browser-use with vision off** as an extra variant (fairer to it with gpt-4o-mini)? — your call.
- **AWM-style baseline** (named in how_work.md) — not built yet.
- More external agents to compare (e.g. Skyvern, Notte, LaVague) — only if you want them.
- Items in my earlier list that may go against your plan (you asked; nothing changed yet):
  1. I called contribution (c) "per-task-type reuse policies" weak — your plan lists it as a contribution.
  2. Benchmark runs set `use_vector_memory = False` (ChromaDB off) — your design includes it.
  3. Benchmark auto-accepts the scraping sample (your flow has user confirmation).
  4. My claim wording ("cost scales with site drift") is in the skill / memory — rewrite in your words?
  5. Ablation switches added to Ecogent core code (off by default).

## 4. Your manual work (from `benchmark_manual_testing.md`)
1. Settings: main + cheap model, prices with date, temperature 0; commit code.
2. Free checks: `python -m bench.lab.selftest`, `python -m bench.lab.fake_run bench/results/fake`.
3. Pilot run (4 tasks), read `pilot_summary.md`.
4. Full run in batches, ablations, figures.
5. Real-world study: 32 cases, weekly rounds (`bench/real_log.py`).
6. Hand-test Claude / Perplexity / Antigravity with `bench/lab/serve.py`.
7. Later: portable .exe for users (PyInstaller) — after code is final; it does not replace releasing source + lab.

## 5. Useful commands
```bash
python -m bench.lab.selftest                                   # LAB OK
python -m bench.lab.fake_run bench/results/fake                 # FAKE RUN OK
python bench/drift_bench.py --tasks papers_caching --variants browser_use --levels 0 --seeds 1 \
    --price gpt-4o-mini=0.15,0.60,0.075 --out bench/results/test.csv --max-steps 30 --timeout 420
python bench/summarize.py bench/results/test.csv
python bench/plot.py bench/results/test.csv --out bench/results/figures
```
Agent tests: `.venv/Scripts/python .claude/skills/ecogent/scripts/e2e_fake_llm.py .claude/skills/ecogent/site <dir>/home` → `ALL OK`.
