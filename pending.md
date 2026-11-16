# Pending — where the work stopped (2026-11-16)

> To continue with Claude: open the repo and say "read pending.md and continue".
> **Base idea: `Ecogent_Works_Doc/how_work.md`** (the original design: task types, plan.json / current_task.json,
> element-finding ladder, validation elements, self-healing, the scraping pattern). Everything here builds on it.
> How everything is built: `Ecogent_Works_Doc/manual.md`. Automatic vs manual benchmark work:
> `Ecogent_Works_Doc/benchmark_auto_vs_manual.md`.

---

## 1. Done since 2026-11-13

- Test shop "Northwind Market" (`test_shop/`, port 3010) + Test Lab window; 9 held-out shop tasks, levels 0-9.
- Paper mode (Benchmark → Experiment): presets, reproducibility checklist, meta file, paper report.
- Validation tests (all pass): Lab integrity, Pipeline (mock LLM, lab + shop), Lab / Shop visual invariance,
  Shop oracle, Shop task-completion, Model routing (`bench/routing_check.py`).
- Baselines checked with a real model (gpt-4o-mini): Stagehand and browser-use failures are the agents' own
  (made-up results, parallel clicks; going back to the empty search page). Runner records cost on timeouts,
  `agent.log`, Stagehand cache counts. browser-use vision-off variant added.
- Settings: temperature 0; searchable model list; show / hide API key.
- Models now: main `openai/gpt-4.1`, cheap `gpt-4o-mini` (OpenRouter). Routing verified on real tasks.
- **Bug fixed (important for the paper):** a step check with a template (`{{user.full_name}}`) was never filled
  in, and typed field values did not count, so every automation rerun "failed" the check and paid for a heal.
  `jobs_python` rerun on an unchanged site: 14 calls / failed → **0 calls / passed**. Regression test added to
  the pipeline test (it fails on the old code, passes on the new).
- All checks pass on the current code (2026-11-16): end-to-end test (mock LLM) `ALL OK`, pipeline test (mock LLM)
  `lab pipeline OK` / `shop pipeline OK` / `FAKE RUN OK`, model routing `ROUTING OK` (with real calls).
- `Ecogent_Works_Doc/manual.md` written (structure, task flow, element ladder, model routing, benchmark).

## 2. Not committed yet

This session's code (fix above, routing check, settings window, shop pilot preset, docs). Commit + tag before any
paper run; then re-run the validation tests at that commit (the checklist only accepts the current commit).

## 3. Real results so far (gpt-4.1 + gpt-4o-mini, seed 1, 2026-11-16, scratch only)

| Task | Cold run | Rerun, no change | Rerun, level 3 | Second rerun, level 3 |
|---|---|---|---|---|
| `papers_caching` (analysis) | pass, 3 calls, $0.009 | pass, 0 calls | pass, 1 call | pass, 0 calls |
| `jobs_python` (automation) | 3/4 jobs, 34 calls, $0.040 | pass, 0 calls | 3/4, 19 calls | pass, 0 calls |

Not paper data (scratch folder, uncommitted code, 1 seed).

## 4. Ready for a paper? (assessment 2026-11-16)

**Not yet.** The system and the benchmark tooling are nearly ready; the paper needs **results**, which do not exist yet.

| Part | Status | Enough for a paper? |
|---|---|---|
| Ecogent (the agent) | built, tested, reuse verified with real models | ✅ mostly; first runs on automation are still weak |
| Benchmark tooling (lab, test shop, oracles, runner, Paper mode, validation tests) | built and checked | ✅ yes |
| Baselines | Stagehand + browser-use run; both fail with gpt-4o-mini | ⚠️ need a model where they succeed, plus at least one cost-focused competitor (Stagehand with a working cache, or workflow-use) |
| **Experimental results** | 2 tasks, 1 seed, scratch only | ❌ **nothing usable yet** |
| Statistics (5 seeds, confidence intervals, paired tests, break-even) | code ready, no data | ❌ |
| Ablations (what each part contributes) | code ready, no data | ❌ |
| Second model family | not started | ❌ (reviewers usually ask) |
| Real-world study / public benchmark | not started | ⚠️ needed against "self-built benchmark" criticism |
| Paper text | not started | ❌ |

Minimum for a credible submission:
1. Commit + tag, pre-registration, validation tests passed at that commit.
2. Shop pilot; fix anything it reveals **before** freezing the code.
3. Main comparison (lab + shop, 5 seeds); external baselines may run on fewer levels to fit the budget.
4. At least one cost-focused competitor that actually works.
5. Ablations (ladder rungs, `no_repair`, `no_cheap`).
6. One more model family, even on a subset.
7. The paper: method, results, where Ecogent does not save, threats to validity, AI-use disclosure.

Optional, raises acceptance a lot: real-world study (32 cases), manual agents, AWM-style baseline.

Rough cost of the full main runs with gpt-4.1: about $300-650 and 1-2 weeks of running (the external baselines
are ~80% of it); the pilot gives the exact numbers.

## 4b. Gaps (code side: Claude; research side: you)

Code / method:
- First runs of automation tasks are expensive and can fail (`jobs_python`: 34 calls, 3 of 4 jobs). Check the
  pilot results for the same pattern on other tasks before freezing the code.
- Contribution (c), per-task-type reuse policies, has no experiment that isolates it.
- Method details to state in the paper: vector memory off in the benchmark, scraping sample auto-accepted.

Research (yours):
- Pre-registration (`bench/preregistration.md`), prices + price date in Benchmark → Configuration.
- Shop pilot (Experiment → "Pilot study: test shop"), then 5-seed lab + shop runs, ablations.
- Second model family; manual agents; real-world study; AWM-style baseline decision.
- `how_work.md` still lists the tiny local LLM; `google_research.md` has unverified citations (#10, #13).
- Paper: venue, IEEEtran draft, verified `.bib`, threats to validity, IEEE AI-use disclosure.

## 5. Final repo cleanup (you, after the experiments)

Plan: keep only the code, replace the working notes with formal docs. Do it **after** the paper runs, on a new
commit, because every result's manifest points to the commit it ran on (keep that tag).

| Keep (code + paper artifact) | Remove or replace | Careful |
|---|---|---|
| `ecogent/`, `bench/` (minus `results/`), `test_shop/`, `README.md`, `pyproject.toml`, `requirements.txt`, `.gitignore` | `pending.md`, `Ecogent_Works_Doc/` working notes, `research/` drafts → formal docs (e.g. `docs/`: design from `how_work.md` (the base idea; update it first: no tiny local LLM, software test = future work), architecture from `manual.md`, benchmark guide, test shop) | `.claude/skills/ecogent/` holds tests: `scripts/e2e_fake_llm.py`, `gui_smoke.py`, `gui_flow.py` and their test pages `site/`. Move them to `tests/` before deleting `.claude/`, or the end-to-end test is lost |

Ask Claude to do the move (tests → `tests/`, update paths in code and docs) when you are ready.
