---
name: ecogent
description: Work on the Ecogent browser agent in this repo (ecogent/ package, DearPyGui app, playwright_browser_manager). Use before changing, debugging, extending or testing any Ecogent code - task types (analysis, scraping, automation, software test), plan.json/current_task.json, executor and element cache, scraping pattern, analysis + relevance filter, LLM prompts/routing/token cost, GUI dialogs, the cost benchmark - and to run the fake-LLM end-to-end and GUI tests.
---

# Ecogent development

The design spec is `Ecogent_Works_Doc/how_work.md`; it is the only source of truth for behaviour
(except its "Tiny Local LLM" technology line, which is outdated - see Project scope).
`research/` and the `Ecogent_Works_Doc/*_research.md` files are thesis/literature notes, not code.

## Project scope (decided 2026-11-08)
- Ecogent is a **browser-only agent**. The earlier plan (a general "standard" agent with a local
  tiny-LLM "NLP Supervisor" routing to Coding / Browser / Testing sub-agents) was dropped.
- **No local / tiny model.** Two API models only: the main (strong) model and an optional cheap
  model for low-level jobs (`cheap_llm` + `cheap_purposes`; the cheap model took the old tiny
  model's role). Do not add Ollama / localhost model support back.
- **The paper drafts are invalid.** `research/Ecogent_Thesis_Proposal_Draft/` (and the
  `research/Proposal/` material) describe the old plan - do not use them as a spec, do not cite
  their claims, and do not edit them. The paper will be rewritten from scratch by the user
  **after the benchmark**.
- **Benchmark plan:** compare Ecogent against other browser agents (e.g. browser-use, Stagehand,
  Skyvern) and general agents with browsing (e.g. Claude, Antigravity, Perplexity) on tokens /
  dollar cost, success rate and repeat-run cost, including deliberate site changes. Contribution
  claim to test: after the first run, LLM cost scales with site drift, not task length (cheapest-
  first element ladder, healing only broken steps, per-task-type reuse policies).
- **Target: IEEE publication.** Benchmark work must be reproducible: scripted drift levels on local
  copies / self-hosted sites, N runs, model + price per dollar figure, measurable baselines
  (browser-use, Stagehand cache+selfHeal, compile-once-no-repair, Ecogent without the ladder).
  Consumer agents (Claude app, Perplexity, Antigravity) report no tokens: success/time only.
  Prior art the paper must cite: Agentic Compilation (arXiv 2604.09718), Agentic Plan Caching,
  AgentRR, Stagehand, workflow-use, Similo, AutoCrawler.

## Core idea (keep it intact)
Ecogent exists to cut LLM token cost. The LLM only plans, picks elements that cannot be found
locally, heals failures and analyzes. Python executes every step and stores what worked in
`plan.json`, so a rerun costs ~0 tokens. Any change that adds LLM calls or prompt size to a hot
path is a regression - check the tests and the cost rules below.

## Architecture (`ecogent/`)
| File | Role |
|---|---|
| `core.py` | `EcogentAgent`: `new_chat`, `initialize` (same request as a finished chat -> `_exact_reference` reuses its plan with NO planning call; similar request (>=0.75) -> planner gets `prompts.ADAPT_HINT` + reference and may answer with a `plan_updates`/`step_changes` patch; else full plan. `_inherit_memory` copies element memory. `plan["origin"]` = what the request itself produced; follow-ups that change the plan set `plan["changed_by_followup"]`, and then reuse starts from `origin`), `follow_up` (`_local_follow_up` first: "run it again" / "same as docx" with no LLM; else LLM decision rerun/heal/extend/reanalyze/reply, heal/extend return a `step_changes` patch applied by `apply_step_changes`), `prepare_requirements`, `execute`, `rerun`, `reanalyze`, schedule offer |
| `executor.py` | Runs steps (see "Element lookup"). Heal loop (short `prompts.heal_system`; `max_heal_attempts` per step, `max_heals_per_run`), then the bounded ReAct fallback `_rescue` (purpose `rescue`, prompt `RESCUE`: up to `max_rescue_turns` moves on one step, `max_rescues_per_run`, only click/fill/press/select_option/wait steps without `on_fail: skip`; each turn = step + moves so far + 30 element lines; the step's own value is used for its own action; on success the element is remembered and helper moves are inserted as `optional` prep steps `<id>_r<n>` - an optional step never calls the LLM, it raises `NoHeal` and is skipped), per-run token budget (`_budget_check` hooked into `LLMRouter.before_call`, asks via `ui.confirm`, headless stops with `BudgetExceeded`), `NeedsUser` -> `ui.hold`, `for_each` with dedupe (first `LOOP_FAIL_FAST`=3 items all failing -> `NoHeal`, loop stopped; any failed item -> run status `partial`), `_check_session` (needs_login tasks: redirected to a login form -> `NeedsUser`, see `pr.detect_login_wall`), `collect_links` with link-signature cache (first run offers `pr.links_to_offer`: menu + repeated-text links cut while >= 2x limit remain, max 80; a rerun whose remembered link shapes match < half of `link_count` picks again), `write_output`. `steps.json` tokens are per step, nested steps excluded (`_tok_frames`) |
| `scraping.py` | Programmatic pattern: `repeating_groups` -> `PATTERN` -> apply -> free `local_problems` checks -> `VALIDATE` -> user sample confirm -> paginate. Confirmed pattern + fill rates in `plan["pattern"]`; reruns reuse it with 0 calls. `scrape_all` stops on pages with no new UNFILTERED records (a fully filtered page does not end it) and `_wait_for_new` waits for JS pagination |
| `analysis.py` | `relevance.select` (BM25 filter to `analysis_budget_chars`) -> one direct call, or map (`analyze_map`, notes cached in temp/notes) + reduce. Final deliverable cached by hash of prompt (`_final_cache`): unchanged sources + request = 0 calls. Tables via `ANALYZE_ROWS` |
| `relevance.py` | Pure-Python BM25: `select(texts, goal, budget)` keeps the best paragraph chunks per source (fair shares, first chunk kept, page order kept) |
| `page_reader.py` | BeautifulSoup only, and the token diet: `candidates` (+ `score`, deduped) / `candidates_for_prompt` (compact `<tag k=v> text` lines), `obvious_choice`, `css_selector`, `main_text` (`_content_root`, noise blocks/lines removed), `page_outline` (hashed classes dropped, wrappers skipped, repeated siblings collapsed after `REPEAT_SHOW`), `links` (content first, `chrome` flag) / `links_for_prompt`, `short_url`, `clean_classes`, `compact_html`, `repeating_groups`, `detect_blocker` |
| `browser.py` | Wraps `playwright_browser_manager.BrowserManager` (sync Playwright, shared instance). `describe(selector)` returns the element identity `{tag, text, attrs}`; `visible_many` (batch visibility); element actions use `action_timeout` (<=10s, page loads keep `page_timeout_ms`) |
| `llm.py` | HTTP clients (OpenAI-compatible `/chat/completions`, Anthropic `/v1/messages`): retry/backoff on 429/5xx/network, JSON mode (auto-off if the server rejects it), cacheable system prompt, usage incl. `cached_input_tokens`. `LLMRouter`: main vs cheap model by purpose, `:fallback` purpose when the cheap model fails, `before_call` hook, `ask_json` -> free `_repair` -> cheap `repair` call (broken reply only) |
| `prompts.py` | All prompts/schemas. `system(type, ...)` = terse `CORE` + `toolbox.catalog(type)` + type guide; `heal_system(type)` is the short heal prompt |
| `toolbox.py` / `tools.py` | Tool registry (per task type, compact `catalog`) / sandboxed built-in file operations |
| `config.py` | `Settings`, `PROVIDERS`, `LLM_PURPOSES`, `CHEAP_PURPOSES_DEFAULT`, `NOT_IMPLEMENTED_TYPES`; browser: `default_profile` ("default", persistent, created on first use; "" = temp), `page_wait_s`, `bot_check_wait_s` (per-task overrides in chat meta `page_wait` / `bot_wait`) |
| `storage.py` | `ChatSession`: `<home>/chats/<id>/` plan.json, current_task.json, steps.json, chat.json (usage by purpose incl. cached tokens), user_info.json |
| `memory.py` | ChromaDB (fallback difflib) similar-plan lookup; `exact` (same normalized request via `normalize_request`, index stores `request`); `compact_plan_reference` |
| `bridge.py` | `UIBridge` events + blocking requests (hold, confirm, sample, user_info, choose); `HeadlessBridge` never blocks (confirm -> None) |
| `worker.py` / `scheduler.py` | Single worker thread job queue; schedules.json periodic runs |
| `integration.py` / `__main__.py` | Tool-call entry (task_type + intent), CLI; no args = GUI |
| `gui/app.py`, `gui/dialogs.py`, `gui/style.py` | DearPyGui app; Settings tabs General / Main LLM / Cheap model / Advanced. `style.py` theme tags are global DPG aliases - never reuse one as a widget tag |
| `bench/benchmark.py` (repo root) | Real-LLM cost benchmark: tasks x N runs, `--mode cached` vs `nocache` (fresh chat, no memory = baseline), CSV of tokens / cached / USD per run. Example tasks in `bench/tasks.example.json`; `bench/results*.csv` is git-ignored |

## Element lookup (`Executor.resolve`) - cheapest first
1. Cached `selector`, accepted only if `browser.describe()` matches the stored identity (`_identity`:
   tag + stable attrs `STABLE_ATTRS`, text unless `dynamic_text`; generated ids ignored).
2. Stored `alternates` (id / test-id / name / aria-label / placeholder / `tag:text-is()`), same check.
3. `_local_refind`: score page candidates against the remembered element (`_match_score`), only a clear winner.
4. `pr.obvious_choice`: the only fitting candidate, or a strong, well-ahead score.
   Every candidate list (lookup, local re-find, heal, rescue) first goes through `Executor._visible`
   (`browser.visible_many`: one JS call, Playwright's visibility rule) - soup cannot see CSS-hidden elements.
5. LLM: `PICK` level 1 (15 candidates) -> level 2 (60) -> `LOCATE` with `pr.focus_outline` (target-matching
   lines + ancestors, <=3000 chars) -> `LOCATE` with the full `page_outline`. Only the full view may raise `NeedsUser`.
Memory lives in `plan.execution.steps[<key>]` (`MEMORY_FIELDS`); a templated target (`{{item}}`) uses
`<key>@<hash of rendered target>`. Stats: `cache_hits`, `local_heals`, `local_picks`, `llm_lookups`, `healed`.

## Small-model guards (found with real gpt-4o-mini runs, all free)
- `core._find_steps`: steps nested in `plan` or named `steps` are accepted.
- `toolbox.guess` / `repair_steps`: wrong action names ("Browser", "Page data", "Results", "open url") mapped
  to real tools at plan time and in `Executor.dispatch`. `catalog` is a flat list (group headings were used as actions).
- `core.ensure_deliverable`: adds a missing `write_output` (scraping) / `analyze` (analysis) step.
- Heal may not change the action of `Executor.KEEP_ACTION` steps; a run with no output file is `partial`
  (never reused); `_reset_data` clears `output_file` and, except for automation, dedupe `processed`.
- Scraping: `many` fields join all matches (tags); `pagination: none` is overridden when max_pages > 1 and a
  Next link exists; `next_page_candidates` handles "Next →" and `li.next > a`; validator sees cut values as "…".
- `collect_links` also stores `link_hrefs` (exact links); analysis cache is shared in `<home>/cache/analysis`.
- `open_url` checks the HTTP status; on 4xx/5xx `_find_by_link` opens the site root and takes the clear best link
  (path similarity + words), saving the URL into the step (guessed deep URLs). Templated URLs are not rewritten.
- A model's "need user" (PICK/LOCATE/rescue/heal ask_user) only pauses when `_human_wall()` sees a captcha or
  login form; otherwise the element counts as not found (heal / ReAct fallback continue).
- `core.ensure_start` inserts `open_url <destination.start_url>` when a plan acts on a page before opening one.
- `collect_links`: PICK_LINKS returning [] falls back to `pr.result_group` (one clear repeated content-link group).
- Scraping with 0 matching records writes a header-only file; the validator is told when its sample is unfiltered.
- Every run starts without `output_file`. Real-LLM runs: visible browser, the user solves captchas (popup).
- Captchas / bot walls (all free): `open_url` with HTTP 403/429 -> `_wait_out_blocker` (re-checks a
  verification screen for `bot_wait` s, Cloudflare passes by itself) else `NeedsUser` - never heal / `_find_by_link`.
  After a hold, `_after_human` waits for redirects and `_resumed` lets `open_url` skip reloading when
  `browser.same_page(url)`; `browser.goto` survives "interrupted by another navigation". New tasks use the
  persistent `default` profile (cookies keep Google's captcha exemption); a temp profile gets captchas.

## Cost rules (check every change against these)
- Reruns must make 0 LLM calls for scraping/automation and for analysis with unchanged sources.
- Never send raw HTML or whole pages: go through `page_reader` (compact lines, `short_url`, `clean_classes`)
  and, for analysis, `relevance.select`.
- Planner/heal prompts stay terse; don't ask the LLM for fields no code reads (output tokens cost 4-5x).
- Follow-ups: handle locally when possible (`_local_follow_up`), otherwise patches (`step_changes`), not full plans.
- Simple jobs carry their own purpose so they can go to the cheap model (`pick`, `validate`, `analyze_map`,
  `classify`, `repair`); add a new purpose to `LLM_PURPOSES` (and the defaults if it is simple).
- Any new LLM path must pass through `LLMRouter.ask/ask_json` (usage accounting, budget, retries).

## Settings that affect cost (`ecogent_data/settings.json`, Advanced tab)
`max_heal_attempts` (2/step), `max_heals_per_run` (6), `max_rescue_turns` (3, 0 = off), `max_rescues_per_run` (2), `max_run_tokens` (150000, 0 = off),
`analysis_budget_chars` (24000, 0 = off), `analysis_direct_chars` (30000), `max_page_chars` (12000),
`scrape_sample_size` (15). Cheap model = `cheap_llm` + `cheap_purposes` (old `local_llm` /
`local_purposes` keys are read and migrated by `Settings._from_dict`; an old Ollama/localhost config
is reset by `_api_only`; provider "none" = off, then everything goes to the main model).
Providers: openai, openrouter, compatible (any OpenAI-compatible API), anthropic.

## Rules that bite
- **Threads:** all Playwright/BrowserManager calls run on the worker thread (sync API + shared
  instance). The GUI never touches the browser; it submits jobs via `worker.submit`.
- **GUI:** DearPyGui with `manual_callback_management=True`; the main loop runs callbacks, `_poll()`
  for `UIEvent`s, renders, then `dialogs.show_pending()`. Dialogs are non-blocking and answer through
  callbacks. New dialogs subclass `Dialog` (created hidden, shown 2 frames later - ImGui cannot open a
  modal in the frame another one closed). New Settings fields: add the widget and the key in `SettingsDialog.ok`.
- **Agent -> GUI questions** go through `UIBridge.request(...)`; add a matching branch in `EcogentApp._request`.
- **Tools (step actions)** are defined once in `toolbox.TOOLS`. To add/change one: edit the `Tool` and
  add/edit `Executor.act_<name>(step, key)` (an import-time assert checks handlers). `dispatch()` rejects
  tools not allowed for the chat's type.
- **Built-in file tools** (`tools.FileTools`) are sandboxed to chat / temp / output / selected folder.
  Never widen the roots; `read_file as_data=true` feeds `analyze`.
- **Step ids** are cache keys (`plan.execution.steps[<id>]`, nested `parent.child`). Keep them stable;
  `apply_step_changes` gives new steps `n<k>` ids that never collide.
- **Software Test** is a placeholder (`config.NOT_IMPLEMENTED_TYPES`); don't add test logic unless asked.
- BrowserManager prints emoji; `browser._safe_console()` protects cp1252 consoles. If no browser is
  found it would call `input()`; `BrowserSession._new_manager` falls back to Playwright Chromium.
- User data lives in `ecogent_data/` (git-ignored; `settings.json` holds API keys). Never commit it.
- **Editing from the shell:** inline Python heredocs in the Bash tool turn `\n` inside string literals
  into real newlines (broke `toolbox.py` / `dialogs.py` once). Use Edit/Write for code, or `chr(10)`.

## Run
```bash
.venv/Scripts/python -m ecogent                       # GUI
.venv/Scripts/python -m ecogent --type analysis "..." # headless, prints JSON
.venv/Scripts/python bench/benchmark.py --tasks bench/tasks.example.json --runs 5 --mode cached --price-in 0.15 --price-out 0.60
```

## Verify changes (always, use a scratch dir for outputs)
From the repo root, with `PYTHONPATH="$PWD"`:
1. `.venv/Scripts/python -m compileall -q ecogent bench`
2. `.venv/Scripts/python .claude/skills/ecogent/scripts/e2e_fake_llm.py .claude/skills/ecogent/site <scratch>/home`
   -> must print `UNIT OK` and `ALL OK`. Expected call lists:
   - scraping finds 6 records (site page 2 has no match, page 3 does); analysis first run `['plan', 'links', 'analyze']` (no `pick`: 2 local picks); RERUN, DRIFT, DRIFT 2,
     "run it again" and "same as a Word document" -> `[]`; LLM follow-up -> `['followup', 'analyze']`
   - BUDGET -> status failed after `plan` + one call; scraping/automation reruns -> `[]`
   - EXACT REPEAT (same request, new chat) -> `[]` (shared analysis cache), output `.md` (origin plan, not the docx follow-up);
     PATCHED PLAN -> `['plan', 'analyze']`; SCRAPE EXACT REPEAT -> `[]`
   - RESCUE (`site/rescue.html`, hidden code box) -> `['plan','pick','locate','heal','rescue','rescue']` (the hidden box is filtered out, never offered), plan gets `s2_r1`;
     RESCUE RERUN -> `[]`; BROKEN LOOP -> failed after `plan` + 3 heals; prep element gone -> `[]` with 1 skipped
   The script serves a copy of `site/` with `Cache-Control: no-store` (the drift test edits pages).
   New LLM prompt path: extend `fake_complete` (and `fake` in gui_flow.py); both fakes take `json_mode`.
3. GUI changes: `.venv/Scripts/python .claude/skills/ecogent/scripts/gui_smoke.py <scratch>/gui`, then read
   the PNGs; for agent<->GUI flows also `gui_flow.py .claude/skills/ecogent/site <scratch>/flow`
   (expect `chat: Baby products done`, `accepted sample via GUI: True`).
4. Cost claims need real numbers: run `bench/benchmark.py` in both modes (needs the user's API key - ask).

The scripts start a local HTTP server on ports 8765/8766 and a real headless browser through
BrowserManager (debug ports 9231/9241); close stray browsers if a port is busy.
