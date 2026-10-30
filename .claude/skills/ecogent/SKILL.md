---
name: ecogent
description: Work on the Ecogent browser agent in this repo (ecogent/ package, DearPyGui app, playwright_browser_manager). Use before changing, debugging, extending or testing any Ecogent code - task types (analysis, scraping, automation, software test), plan.json/current_task.json, executor, scraping pattern, LLM prompts, GUI dialogs - and to run the fake-LLM end-to-end and GUI tests.
---

# Ecogent development

The design spec is `Ecogent_Works_Doc/how_work.md`; it is the only source of truth for behaviour.
Ignore `research/` (thesis draft, proposal, papers): it is documentation, not code.

## Core idea (keep it intact)
The LLM only plans, picks elements on a cache miss, heals failures and analyzes. Python executes
every step and stores what worked in `plan.json`, so a rerun should cost ~0 LLM tokens.
Any change that adds LLM calls to the rerun path is a regression - check the tests below.

## Architecture (`ecogent/`)
| File | Role |
|---|---|
| `core.py` | `EcogentAgent`: new chat, `initialize` (LLM -> plan + current_task), `follow_up` (decision rerun/heal/extend/reanalyze/reply), `prepare_requirements` (login profile, user info), `execute`, `rerun`, schedule offer |
| `executor.py` | Runs steps. `resolve()` ladder: cached selector + fingerprint check -> `PICK` with probable elements (level 1) -> all interactive (level 2) -> `LOCATE` with page outline. Heal loop, `NeedsUser` -> `ui.hold`, `for_each` with dedupe, `collect_links` with link-signature cache, `write_output` |
| `scraping.py` | Programmatic pattern: `repeating_groups` -> `PATTERN` -> apply -> `VALIDATE` -> user sample confirm -> paginate. Confirmed pattern + fill rates saved in `plan["pattern"]` |
| `analysis.py` | One-call or map (cached notes in temp/notes) + reduce; table formats via `ANALYZE_ROWS` |
| `page_reader.py` | BeautifulSoup only: `candidates`, `css_selector`, `main_text`, `page_outline`, `detect_blocker`, `links`, `repeating_groups` |
| `browser.py` | Wraps `playwright_browser_manager.BrowserManager` (sync Playwright, shared instance) |
| `toolbox.py` / `tools.py` | Tool registry (per task type) / sandboxed built-in file operations |
| `config.PROVIDERS` | LLM presets: openai, openrouter (extra headers), ollama, compatible (custom base URL) all use `/chat/completions`; anthropic uses `/v1/messages`. `LLMClient.list_models()` backs Settings' "Test connection" |
| `gui/style.py` | Design system: palette, fonts, global + named themes (`btn_primary`, `btn_secondary`, `btn_ghost`, `btn_danger`, `pill_*`, `card`, `sidebar`, `bubble_*`, `tile`). Theme tags are global DPG aliases - never reuse one as a widget tag |
| `llm.py` / `prompts.py` | HTTP clients (OpenAI-compatible, Anthropic), `LLMRouter` main/local routing + usage callback, `extract_json`; all system prompts and JSON schemas |
| `storage.py` | `ChatSession`: `<home>/chats/<id>/` plan.json, current_task.json, steps.json, chat.json, user_info.json |
| `bridge.py` | `UIBridge` events + blocking requests (hold, confirm, sample, user_info, choose); `HeadlessBridge` for CLI |
| `worker.py` / `scheduler.py` | Single worker thread job queue; schedules.json periodic runs |
| `memory.py` | ChromaDB (fallback difflib) similar-plan lookup; `core._inherit_memory` copies selectors |
| `integration.py` / `__main__.py` | Tool-call entry (task_type + intent), CLI; no args = GUI |
| `gui/app.py`, `gui/dialogs.py` | DearPyGui app |

## Rules that bite
- **Threads:** all Playwright/BrowserManager calls must run on the worker thread (sync API + shared
  instance). The GUI never touches the browser; it submits jobs via `worker.submit`.
- **GUI:** DearPyGui with `manual_callback_management=True`; the main loop runs callbacks, `_poll()`
  for `UIEvent`s, renders, then `dialogs.show_pending()`. Dialogs are non-blocking and answer through
  callbacks. New dialogs must subclass `Dialog` (created hidden, shown 2 frames later - ImGui cannot
  open a modal in the frame another one closed).
- **Agent -> GUI questions** go through `UIBridge.request(...)`; add a matching branch in `EcogentApp._request`.
- **Tools (step actions)** are defined once in `toolbox.TOOLS` (params, description, group, task types,
  needs-browser). To add/change one: edit the `Tool` there and add/edit `Executor.act_<name>(step, key)`.
  An import-time assert fails if a tool has no handler. `prompts.system(task_type, ...)` sends the LLM
  only that type's tools; `dispatch()` rejects tools not allowed for the chat's type.
- **Built-in file tools** (`tools.FileTools`) are sandboxed: paths resolve against the chat's selected
  folder (`meta.work_folder`, "Folder..." in the GUI) or its output folder, and must stay inside chat /
  temp / output / selected folders. Never widen the roots; `read_file as_data=true` feeds `analyze`.
- **Step ids** are the cache keys (`plan.execution.steps[<id>]`, nested `parent.child`). Keep them stable.
- **Software Test** is a placeholder (`config.NOT_IMPLEMENTED_TYPES`); the user will implement it. Don't
  add test logic unless asked.
- BrowserManager prints emoji; `browser._safe_console()` stops cp1252 consoles from crashing. If no
  browser is found it would call `input()`; `BrowserSession._new_manager` falls back to Playwright Chromium.
- User data lives in `ecogent_data/` (git-ignored; `settings.json` holds API keys). Never commit it.

## Run
```bash
.venv/Scripts/python -m ecogent                       # GUI
.venv/Scripts/python -m ecogent --type analysis "..." # headless, prints JSON
```

## Verify changes (always, use a scratch dir for outputs)
From the repo root, with `PYTHONPATH="$PWD"`:
1. `.venv/Scripts/python -m compileall -q ecogent`
2. `.venv/Scripts/python .claude/skills/ecogent/scripts/e2e_fake_llm.py .claude/skills/ecogent/site <scratch>/home`
   -> must print `ALL OK`. Rerun lines must show `calls: []` for scraping/automation and only
   `['analyze']` for analysis. If you add a new LLM prompt path, extend `fake_complete` in the script.
3. GUI changes: `.venv/Scripts/python .claude/skills/ecogent/scripts/gui_smoke.py <scratch>/gui`, then read
   the PNGs to check layout; for agent<->GUI flows also run `gui_flow.py .claude/skills/ecogent/site <scratch>/flow`.

The scripts start a local HTTP server on ports 8765/8766 and a real headless browser through
BrowserManager (debug ports 9231/9241); close stray browsers if a port is busy.
