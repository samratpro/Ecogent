# Ecogent Manual

> How Ecogent is built: the code structure, how a task runs, how models are routed, and the benchmark system.
> **Base idea: `how_work.md`.** Ecogent's design (task types, per-chat plan files, the element-finding ladder,
> validation elements, self-healing, the scraping pattern) comes from that document; this manual describes how it
> is implemented. Benchmark operation (automatic vs manual): `benchmark_auto_vs_manual.md`.
> Updated 2026-11-16.

---

## 1. What Ecogent is

Ecogent is a **browser agent whose LLM usage decreases with reuse**. The LLM plans, picks elements when the local
lookup fails, heals broken steps and writes the analysis; Python (Playwright + BeautifulSoup) does the actual work and
records what worked in `plan.json`, so a repeated task needs few or zero LLM calls, even after the website changes.

Contributions (from `how_work.md`):
1. a **fallback ladder for finding elements** that uses as few tokens as possible,
2. **plans that carry validation elements**, so only the broken steps are healed,
3. **reuse policies per task type**.

| Task type | Status | Reuse policy |
|---|---|---|
| Analysis | implemented | rerun the saved plan; analysis cache for identical inputs |
| Data scraping | implemented | reuse the saved "programmatic pattern"; heal it only when validation fails |
| Automation | implemented | replay the saved steps; captcha / login handed to the user; schedules |
| Others | implemented | general browser steps |
| Software test | **not implemented** (placeholder in the GUI) | — |

Scope: browser only. Two **API** models (main + cheap); there is no local / tiny model.
Implementation: Python 3.10+, Playwright (through `playwright_browser_manager`), BeautifulSoup, ChromaDB (optional),
JSON files, DearPyGui. The approach itself is not tied to these libraries.

---

## 2. Repository structure

```
Ecogent/
├── ecogent/                    the agent (Python package)
│   ├── __main__.py             python -m ecogent  -> GUI;  --type analysis "..." -> headless run
│   ├── config.py               Settings, providers, task types, LLM purposes, ablation flags
│   ├── core.py                 orchestrator: new chat, plan, run, follow-ups, reruns
│   ├── executor.py             runs current_task.json step by step: element ladder, healing, rescue, budget
│   ├── page_reader.py          BeautifulSoup: candidate elements, context ladder, page outline, login/captcha detection
│   ├── browser.py              browser control on top of BrowserManager (one thread)
│   ├── scraping.py             programmatic pattern: propose -> sample -> validate -> heal -> scrape
│   ├── analysis.py             analysis of collected pages (BM25 filter, one call or map + reduce)
│   ├── relevance.py            pure-Python BM25 relevance filter
│   ├── llm.py                  LLMClient (OpenAI-style / Anthropic over HTTP), LLMRouter (model routing)
│   ├── prompts.py              system prompts (plan, pick, locate, heal, rescue, pattern, validate, analyze, ...)
│   ├── toolbox.py              registry of step actions the LLM may use (per task type)
│   ├── tools.py                local file tools, restricted to allowed folders
│   ├── storage.py              per-chat workspace (plan.json, current_task.json, steps.json, chat.json)
│   ├── memory.py               plan memory across chats (ChromaDB or fuzzy match)
│   ├── output.py               final deliverables (md, docx, json, csv, xlsx, ...)
│   ├── scheduler.py            periodic runs for automation chats
│   ├── worker.py               worker thread: all agent + browser work, one job at a time
│   ├── bridge.py               agent <-> UI (hold for captcha, confirm sample, ...); headless bridge for CLI
│   ├── integration.py          use Ecogent from another agent (tool call; task type + intent required)
│   ├── bench_runner.py         benchmark logic for the app (config, command, schedule, results)
│   ├── paper_mode.py           experiment presets, reproducibility checklist, meta file, paper report
│   ├── test_shop.py            start / stop the test shop, its lab API
│   └── gui/
│       ├── app.py              main window: sidebar, task list, chat, activity panel
│       ├── dialogs.py          new task, settings, hold, user info, schedules, profiles, ...
│       ├── benchmark.py        Benchmark window (Experiment, Results, Configuration, Log, Schedule)
│       ├── testlab.py          Test Lab window (test shop server, scenarios, validation)
│       └── style.py            design system: colours, fonts, icons, button themes
├── bench/                      the benchmark (the paper's methodology)
│   ├── drift_bench.py          main runner: tasks x systems x drift levels x seeds -> CSV + manifest
│   ├── lab/                    lab sites with ground truth
│   │   ├── sites.py            shop + cart, papers, jobs, CRM (login), popup, table, load more, notes, deal wizard
│   │   ├── drift.py            seeded website changes, levels 0-4
│   │   ├── tasks.py            24 lab tasks + oracles
│   │   ├── server.py           HTTP server for the lab sites
│   │   ├── serve.py            manual console for hand-driven agents (Claude in Chrome, Comet, ...)
│   │   ├── selftest.py         Lab integrity test             -> LAB OK
│   │   ├── fake_run.py         Pipeline test (mock LLM)       -> FAKE RUN OK
│   │   └── look_check.py       Lab visual invariance test     -> LAB LOOK OK
│   ├── shop_tasks.py           9 held-out tasks on the test shop + oracles, levels 0-9
│   ├── shop_selftest.py        Shop oracle test               -> SHOP TASKS OK
│   ├── routing_check.py        model routing check            -> ROUTING OK
│   ├── baselines/              Stagehand (Node) and browser-use (.venv-baselines) runners
│   ├── summarize.py            statistics tables (mean ± sd, 95% CI, paired tests, cost of ownership)
│   ├── plot.py                 figures (SVG)
│   ├── real_log.py             real-world study log (manual)
│   └── results/                CSV results (git-ignored)
├── test_shop/                  "Northwind Market": neutral React + Node test shop on port 3010
├── Ecogent_Works_Doc/          design and research documents (this file)
├── .claude/skills/ecogent/     developer notes + GUI / flow test scripts
└── ecogent_data/               settings, chats, profiles, benchmark config (git-ignored; holds API keys)
```

---

## 3. Runtime architecture

```
 GUI thread (DearPyGui)                      worker thread (one job at a time)
 ┌──────────────────────┐   jobs            ┌───────────────────────────────────────────┐
 │ app.py / dialogs.py  │ ───────────────▶  │ core.py  (Ecogent)                        │
 │ benchmark.py         │                   │   ├─ executor.py   steps, ladder, healing │
 │ testlab.py           │ ◀─────────────── │   ├─ scraping.py   pattern               │
 └──────────────────────┘  UI events        │   ├─ analysis.py   final deliverable     │
        ▲      │            (bridge.py)     │   ├─ browser.py + page_reader.py         │
        │      └── hold / confirm ────────▶ │   └─ llm.py  LLMRouter ──▶ main / cheap │
        │                                   └───────────────────────────────────────────┘
        └── benchmark and test shop run as separate processes (drift_bench.py, node server.js)
```

- Playwright's sync API must stay on one thread, so **all browser and agent work runs on the worker thread**
  (`worker.py`); the GUI only sends jobs and receives events.
- When the agent needs a person (captcha, login, sample confirmation, missing user info), it calls the **bridge**,
  which shows a dialog and waits for the answer. The headless bridge answers automatically (CLI, tool calls).
- The benchmark never runs inside the app process: the app starts `bench/drift_bench.py` as a child process, so
  the numbers in the window are exactly those a terminal run produces.

---

## 4. How a task runs

### 4.1 New task
1. The user picks the **task type** (or another agent passes it through `integration.py`; if it is missing,
   Ecogent classifies the request with the `classify` job and reports its choice).
2. `memory.py` looks for a similar earlier chat. If one exists, its plan is offered to the LLM as a reference and its
   cached selectors are copied, so the new chat starts with warm execution memory.
3. `core.py` sends the user prompt, the core system prompt (`prompts.py`) and **only the tools of that task type**
   (`toolbox.py`) to the main model (`plan` job). The reply is `plan.json` (goal, destination, output,
   requirements) and `current_task.json` (the steps).
4. The executor runs the steps (section 5). Everything that worked is written back into `plan.json`.

### 4.2 Files per chat (`<home>/chats/<chat_id>/`)
| File | Content |
|---|---|
| `plan.json` | goal, destination, output format, execution memory (selectors, identity, alternates, validation elements), scraping pattern, runs |
| `current_task.json` | the steps the executor runs |
| `steps.json` | execution log |
| `chat.json` | meta, messages, memory summary, **token usage by purpose and model** |
| `user_info.json` | facts the user gave for automation (optional) |

### 4.3 Per task type
- **Analysis**: open sources, `get_page_data` into temp files, then `analysis.py`: a BM25 filter keeps only the parts
  of each page that match the goal (within a character budget); small inputs go to one `analyze` call, large ones
  are condensed per page (`analyze_map`) and then combined (`analyze`). The result is written in the requested format.
- **Data scraping** (`scraping.py`): the LLM sees only a few repeated blocks and returns CSS selectors (`pattern`);
  Python applies them, takes a 10-20 record sample, the LLM checks it (`validate`); a bad sample heals the pattern;
  the user confirms the sample; then Python scrapes every page with no further LLM calls. A rerun reuses the pattern
  and heals it only when validation fails.
- **Automation**: steps are replayed; captcha and login walls pause for the user (cookies are kept in the browser
  profile); user information is asked once and stored; `scheduler.py` runs the chat at set times.

### 4.4 Follow-ups and reruns
A follow-up message is classified by the main model (`followup` job) as rerun, heal, extend or reanalyze, so the
existing plan is reused instead of planning from scratch. "Run again" replays the saved plan.

---

## 5. Element lookup ladder and healing (`executor.py`, `page_reader.py`)

For every step that needs an element, the cheapest method that works wins:

| Rung | Method | LLM? | Ablation flag |
|---|---|---|---|
| 1 | cached selector + **identity check** (tag, stable attributes, text) | no | `no_identity` |
| 2 | stored **alternate locators** | no | `no_alternates` |
| 3 | local **re-find** of the remembered element among the page's elements (similarity) | no | `no_refind` |
| 4 | the **obvious candidate** (only one fits / clear winner) | no | `no_obvious` |
| 5 | `pick` from probable elements -> broader area -> page outline (**graded context**) | yes (cheap) | `no_graded` |
| 6 | `locate` (selector from the page outline) | yes (main) | |
| 7 | `heal` the step, then `rescue` (multi-turn) if healing fails | yes (main) | |

`no_repair` (= the `compile_only` baseline) switches off every repair on reruns: no re-find, no LLM, no heal, no
rescue; a broken step simply fails. `no_graded` skips the small LLM views and sends the full outline at once.

- The page reader's **context ladder** sends the LLM as little as possible: level 1 probable elements (e.g. only
  text inputs for a `fill` step), level 2 every interactive element, level 3 the page outline without noise.
- Repairs are **written back** to `plan.json`, so the next run needs no LLM for that step (the benchmark's `rerun2`
  phase measures this: 0 calls means the repair was saved).
- Limits: `max_heal_attempts` per step, `max_heals_per_run`, `max_rescue_turns`, `max_rescues_per_run`, and a
  per-run token budget `max_run_tokens` (asks the user before going over).
- Captcha / login detection pauses the run for the user.

---

## 6. Model routing

### 6.1 Two models
| Setting | Role | Your current setting |
|---|---|---|
| **Main LLM** | strong model: planning, healing, rescue, final analysis | `openai/gpt-4.1` (OpenRouter) |
| **Cheap model** | low-level jobs | `gpt-4o-mini` (OpenRouter) |

Both are cloud API models (OpenAI, OpenRouter, any OpenAI-compatible server, or Anthropic). Temperature 0 for
benchmark runs.

### 6.2 How a job is routed (`llm.py`, `LLMRouter`)
Every LLM call names its **purpose** (the job). The router decides the model by purpose:

```
purpose in settings.cheap_purposes  and  cheap model enabled   ->  cheap model
otherwise                                                     ->  main model
cheap model fails (error)   ->  same request on the main model, recorded as "<purpose>:fallback"
reply is not valid JSON     ->  one short "repair" round-trip with only the broken reply
```

Routing is **by job type**, decided in advance, not a learned router that judges each request (unlike RouteLLM).

### 6.3 The purposes
| Purpose | What it does | Called in | Default model |
|---|---|---|---|
| `plan` | first plan: plan.json + current_task.json | `core.py` | main |
| `followup` | classify a follow-up (rerun / heal / extend / reanalyze) | `core.py` | main |
| `classify` | task type when another agent did not give one | `core.py` | **cheap** |
| `pick` | choose the element from a short candidate list | `executor.py` | **cheap** |
| `locate` | selector from the page outline when picking failed | `executor.py` | main |
| `heal` | repair a failed step | `executor.py` | main |
| `rescue` | multi-turn recovery when healing failed | `executor.py` | main |
| `pattern` | scraping pattern (CSS selectors) | `scraping.py` | main |
| `validate` | check a scraping sample | `scraping.py` | **cheap** |
| `analyze_map` | per-page notes for large analysis inputs | `analysis.py` | **cheap** |
| `analyze` | final analysis / report | `analysis.py` | main |
| `repair` | fix a reply that was not valid JSON | `llm.py` | **cheap** |

Default cheap list (`CHEAP_PURPOSES_DEFAULT` in `config.py`): `pick, validate, analyze_map, classify, repair`.
**Your saved settings** route only `pick` and `classify` to the cheap model. Change it in Settings → Cheap model.
Report the list you use in the paper: it decides how much routing can save.

### 6.4 Recording
Every call is recorded per chat in `chat.json` (`usage.by_purpose`: calls, input / cached / output tokens and the
`provider:model` that answered). The benchmark copies this into the CSV (`by_purpose`, `main_model`,
`cheap_model`) and prices every token with the model's own price.

### 6.5 Measuring what routing saves
The benchmark variant **`no_cheap`** runs the full system with the cheap model off (every job on the main model).
`ecogent` vs `no_cheap` = the saving from routing; `ecogent` vs `nocache` = the saving from reuse and repair.
Reviewers need both to see which part of the saving comes from where.

### 6.6 Checking the routing
```bash
python bench/routing_check.py          # free: mock clients; every purpose -> expected model, fallback, no_cheap
python bench/routing_check.py --real   # + one tiny real call per model (fraction of a cent)
```
Prints the routing table and `ROUTING OK`. The real mode reports the model name from the provider's reply, so a
wrong model id is caught. Result on 2026-11-16 (gpt-4.1 + gpt-4o-mini): ROUTING OK, both models served as asked.

---

## 7. Where Ecogent reduces cost

The cost of an LLM agent = number of LLM calls × tokens per call × price per token. Ecogent lowers all three.

### 7.1 Fewer LLM calls (the main saving)
| # | Mechanism | Where | Saving |
|---|---|---|---|
| 1 | **Plan reuse**: a rerun replays the saved `current_task.json`; no planning call | `core.py`, `storage.py` | the `plan` call (the largest prompt) is paid once |
| 2 | **Element memory**: cached selector + identity check, alternates, local re-find, obvious candidate (ladder rungs 1-4) | `executor.py` | most element lookups need no LLM on reruns, even after site changes |
| 3 | **Repairs written back**: a healed step is saved into the plan | `executor.py` | a site change is paid for once; the next run is free again (`rerun2` = 0 calls) |
| 4 | **Scraping pattern**: the LLM writes CSS selectors once; Python scrapes every page | `scraping.py` | no LLM call per page or per record; reruns reuse the pattern |
| 5 | **Analysis cache**: per-page notes and the final report are cached by a hash of their exact input | `analysis.py` (`cache/analysis/`) | unchanged pages / identical requests cost nothing; changed pages are re-analysed (stale answers are not reused) |
| 6 | **Link-list memory**: remembered link shapes for `collect_links` | `executor.py` | no new `pick` while the result list keeps its shape |
| 7 | **Memory across chats**: a similar earlier chat gives a reference plan and its selectors | `memory.py` | a new but similar task starts with warm element memory |
| 8 | **Follow-ups reuse the plan** (rerun / heal / extend / reanalyze) instead of planning again | `core.py` (`followup`) | one small classification call instead of a new plan |
| 9 | **Optional helper steps never call the LLM** (skipped if their element is gone) | `executor.py` (`NoHeal`) | no heal spent on steps that are not needed |

### 7.2 Fewer tokens per call
| # | Mechanism | Where |
|---|---|---|
| 10 | **Graded context**: the LLM first sees a short candidate list (probable elements), then a wider one, the full page outline only last | `page_reader.py`, `executor.py` |
| 11 | **Page cleaning**: noise and outliers removed from the outline | `page_reader.py` |
| 12 | **BM25 relevance filter**: only the parts of collected pages that match the goal go to the analysis, within a character budget | `relevance.py`, `analysis.py` |
| 13 | **Only the task type's tools** are listed in the planner prompt; healing uses a short prompt | `toolbox.py`, `prompts.py` (`heal_system`) |
| 14 | **JSON repair sends only the broken reply**, not the original long prompt | `llm.py` |

### 7.3 Cheaper tokens
| # | Mechanism | Where |
|---|---|---|
| 15 | **Model routing**: simple jobs go to the cheap model (section 6) | `llm.py` (`LLMRouter`) |
| 16 | **Provider prompt caching**: the static system prompt is sent first (OpenAI-style providers cache long identical prefixes; Anthropic gets `cache_control`); cached input tokens are priced lower and counted separately | `llm.py` |

### 7.4 Limits on the worst case
| # | Mechanism | Where |
|---|---|---|
| 17 | heal attempts per step and per run, rescue turns per step and per run | `executor.py`, Settings → Advanced |
| 18 | per-run token budget (asks before going over) | `executor.py` (`max_run_tokens`) |
| 19 | a loop stops when its first 3 items all fail | `executor.py` (`LOOP_FAIL_FAST`) |

### 7.5 Where Ecogent does NOT save (state this in the paper)
- **The first run** costs the same as `nocache` (Ecogent without reuse): planning + element picks; for automation it
  can cost more because failed steps are healed (`jobs_python`: 34 calls). Against step-by-step agents (Stagehand,
  browser-use) the first run was already 15-35x cheaper on `papers_caching` (one LLM plan, Python executes; they
  call the LLM with the page at every step), but there they failed the task, and automation first runs have no
  baseline comparison yet.
- **New data**: when the content changes, the analysis is redone (on purpose: a cached answer would be wrong).
- **Large redesigns** and **class names that change on every page load**: the saved plan or element memory stops
  matching, so steps are healed again (this is what the test shop's levels 5, 3 and 9 measure).

### 7.6 Measured so far (preliminary: 1 seed, scratch / pre-fix runs, not paper data)
| Run | Ecogent | Comparison |
|---|---|---|
| `papers_caching`, gpt-4o-mini, levels 0-4 (2026-11-13) | 11/11 passed, 4 calls, **$0.0009** in total | `nocache`: 3 calls and $0.0007 **per run**; Stagehand 0/11, $0.10 |
| `papers_caching`, gpt-4.1 + gpt-4o-mini (2026-11-16) | first run $0.009 (3 calls), reruns $0-0.002 (0-1 calls) | — |
| `jobs_python`, gpt-4.1 + gpt-4o-mini (2026-11-16, after the fix) | first run $0.040 (34 calls); unchanged rerun **0 calls**; after a level-3 change 19 calls, then **0 calls** | — |

How the saving is measured: `ecogent` vs `nocache` (reuse + repair), `ecogent` vs `compile_only` (repair),
`ecogent` vs `no_cheap` (routing), ablations (each ladder rung). Break-even: the number of reruns after which the
first run's extra cost is paid back is computed by `bench/summarize.py` (cost of ownership).

---

## 8. Settings (`ecogent_data/settings.json`, git-ignored)

| Tab | Content |
|---|---|
| General | temp / output / profile folders, browser path (empty = auto-detect), language, headless |
| Main LLM | provider, base URL, API key (eye button shows / hides it), model (**Browse models...** = searchable list), max output tokens, temperature, timeout |
| Cheap model | the same + which purposes go to it |
| Advanced | page timeouts, sample size, page / analysis character budgets, heal / rescue limits, token budget, vector memory |

API keys are never written to benchmark files, meta files or results.

---

## 9. Desktop app (GUI)

| Window | What it is for |
|---|---|
| Main window | task list, chat, plan / steps / memory / files panel, activity log, Run again / Stop |
| New task | task type, prompt, folder, browser profile |
| Settings | section 8 |
| Browser profiles, Schedules | logged-in profiles; periodic automation runs |
| **Benchmark** | Experiment (paper presets + reproducibility checklist), Results, Configuration, Log, Schedule |
| **Test Lab** | test shop server, one-click scenarios (site versions), validation tests |

---

## 10. Benchmark system

### 9.1 Protocol (`bench/drift_bench.py`)
For every task × system × seed (one **cell**): a **cold** run at level 0 (solve from the prompt), then for every
level a **rerun** (saved plan restored, site changed) and a **rerun2** (run again: 0 calls = the repair was saved).
Systems without memory (`nocache`, browser-use) get one fresh run per level. Every run is scored by the task's
**oracle** against ground truth and becomes one CSV row (success, precision, recall, calls, tokens by purpose,
cached tokens, USD, seconds). A manifest stores the git commit, models, prices, levels and the experiment's meta file.

### 9.2 Systems (variants)
| Variant | What it is |
|---|---|
| `ecogent` | full system |
| `nocache` | no reuse: plans every run from scratch |
| `compile_only` | replays the saved plan but never repairs it (`no_repair`) |
| `no_cheap` | cheap model off (section 6.5) |
| ablations | `no_identity`, `no_alternates`, `no_refind`, `no_obvious`, `no_graded`, `no_repair` |
| `stagehand` | Stagehand agent with its own cache (Node, `bench/baselines/stagehand`) |
| `browser_use`, `browser_use_novision` | browser-use with / without screenshots (`.venv-baselines`) |

### 9.3 Environments
- **Lab** (`bench/lab`): 24 tasks (scraping / analysis / automation) on 9 small sites; seeded drift levels 0-4
  (attributes, structure, text, redesign; cumulative). Data, links and form fields are preserved, so every level
  can still be solved.
- **Test shop** (`test_shop/`, `bench/shop_tasks.py`): a realistic React shop, **held out** (Ecogent was never tuned
  on it). 9 tasks, levels 0-9 = one real-world change type each: baseline, markup rebuild, markup refactor,
  per-load markup, navigation change, redesign, copy change, interstitials, data change, combined. Changes are
  server-wide, so every agent sees the same version. Oracles read the ground truth at scoring time, so a stale cached
  answer fails. Fairness rules F1-F9: `test_shop/README.md`.

### 9.4 Paper mode (Benchmark → Experiment)
Presets: main comparison (lab), main comparison (test shop), ablation study, pilot (lab), pilot (test shop).
The **reproducibility checklist** must pass before "Run experiment": clean working tree, git tag, temperature 0,
prices + date, ≥ 5 seeds, baseline coverage, baselines installed, committed pre-registration, validation tests
passed at this commit, new result file (+ warnings: distinct main / cheap model, complete task suite).
"Run with deviations" records every failed check. Each run writes `<name>.meta.json`; "Generate report" writes
`<name>_paper_report.md` (protocol, deviations, statistics, figures).

### 9.5 Validation tests (free, no API cost)
| Test | Command | Success line |
|---|---|---|
| Lab integrity test | `python -m bench.lab.selftest` | `LAB OK` |
| Pipeline test (mock LLM) | `python -m bench.lab.fake_run <scratch dir>` | `lab pipeline OK`, `shop pipeline OK`, `FAKE RUN OK` |
| Lab visual invariance test | `python -m bench.lab.look_check` | `LAB LOOK OK` |
| Shop oracle test | `python -m bench.shop_selftest` | `SHOP TASKS OK` |
| Shop visual invariance test | `python test_shop/check_look.py` | `LOOK OK` |
| Shop task-completion test | `python test_shop/check_flows.py` | `FLOWS OK` |
| Model routing check | `python bench/routing_check.py [--real]` | `ROUTING OK` |

All except the routing check run from the app (Benchmark → Configuration, Test Lab) and are recorded with the
commit; the checklist accepts only results from the current commit. The mock-LLM test checks the plumbing only:
its success numbers are meaningless and never go into the paper.

### 9.6 Results
`bench/results/<name>.csv` + `<name>.manifest.json` (git-ignored). `bench/summarize.py` → statistics tables,
`bench/plot.py` → figures, both also from Benchmark → Results. Per-run folders (plans, outputs, the external
agents' `result.json`, `agent.log`) are under `bench/results/work/`.

### 9.7 Manual parts
Manual agents (success and time only): `python -m bench.lab.serve [--site shop] --system <name> --level <n>`.
Real-world study: `python bench/real_log.py`. Details: `benchmark_manual_testing.md`, `benchmark_auto_vs_manual.md`.

---

## 11. Extending the code

| To add | Do this |
|---|---|
| a step action (tool) | add a `Tool` in `toolbox.py` and an `act_<name>` method in `executor.py`; extend `fake_complete` in `bench/lab/fake_run.py` if the mock test needs it |
| an LLM job | call `router.ask(...)`/`ask_json(...)` with a new purpose, add it to `LLM_PURPOSES` in `config.py` (and to `CHEAP_PURPOSES_DEFAULT` if it is a simple job); `routing_check.py` then covers it |
| a lab task | a `Task` with an oracle in `bench/lab/tasks.py` |
| a shop task | a `Task` in `bench/shop_tasks.py`, but only before the shop is frozen (fairness rule F6) |
| a baseline | a runner in `bench/baselines/` and a branch in `drift_bench.py` (`EXTERNAL`) |
| the software test type | remove it from `NOT_IMPLEMENTED_TYPES` in `config.py` and add its rules, tools and reuse policy |

## 12. Rules for the repository
- `ecogent_data/` (settings with API keys, chats) and `bench/results/` are git-ignored and never committed.
- Commit and tag before every paper run; the manifest records the commit.
- Real-model tests use a visible browser; a person solves captchas.
