# Ecogent

A token-efficient browser agent. The LLM plans, picks elements only when needed, heals
failed steps and analyzes results; Python (Playwright + BeautifulSoup) does the work and
remembers what worked in `plan.json`, so repeated runs need few or zero LLM tokens.

Design: [Ecogent_Works_Doc/how_work.md](Ecogent_Works_Doc/how_work.md)

## How to run

### 1. Install (once)

Requires Python 3.10+ and a Chromium browser (Brave, Edge, Chrome, Comet or Chromium).

**Windows (PowerShell)**
```powershell
cd "path\to\Ecogent"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium   # only needed if no Brave/Edge/Chrome is installed
```

**macOS / Linux**
```bash
cd path/to/Ecogent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Start the desktop app

```bash
python -m ecogent
```

(or `pip install -e .` once, then just `ecogent`)

### 3. Set up the LLM (first start)

Click **Settings**:

- **Main LLM** - pick a provider; the base URL is filled in for you:

  | Provider | Base URL | API key |
  |---|---|---|
  | OpenAI | `https://api.openai.com/v1` | required |
  | OpenRouter | `https://openrouter.ai/api/v1` | required (one key, many models) |
  | Custom OpenAI-compatible | any compatible API, e.g. Groq `https://api.groq.com/openai/v1`, Together, DeepSeek | usually required |
  | Anthropic | `https://api.anthropic.com` | required |

  Press **Test connection / fetch models**, then choose a model from the list (or type it).
- **Cheap model** (optional, recommended) - Ecogent uses two API models: the main (strong) model and a
  cheaper one (e.g. `gpt-4o-mini`, a flash/haiku model) for low-level jobs. Ticked by default: `pick`,
  `validate`, `analyze_map` (per-page notes), `classify`, `repair`. Planning, healing and the final
  analysis stay on the main model. There is no local / tiny model.
- **General** - temp / output / browser-profile folders, browser path (empty = auto-detect),
  headless or graphics mode by default.

Settings are stored in `ecogent_data/settings.json` (git-ignored; it holds your API key).
You can also set the key with the `ECOGENT_API_KEY` environment variable.

### 4. Run a task

1. Click **+ New task**, choose the type (Analysis, Data Scrap, Automation, Others, or
   Auto-detect), optionally a browser profile and headless mode.
2. Type the task in the chat and press **Enter**, e.g.
   *"Search Google Scholar for papers on browser agents and give me a summarized md file"*.
3. Watch the run: the LLM plan appears in the `plan.json` / `current_task.json` tabs, every step in
   `steps.json`, and token usage at the bottom.
4. When Ecogent needs you (captcha, login, confirming scraped sample data) a dialog appears -
   do it in the browser window, then press **Continue**.
5. Results are in **Data & output** (or **Output folder**). Send a follow-up in the same chat
   ("same data as docx", "go deeper", "now the toys category") - Ecogent reuses the plan.
6. **Run again** repeats the task with the cached plan (almost no tokens).

**Automation tasks:** if the site needs a login, Ecogent opens a browser with a new profile -
log in yourself and close the window; the session is reused on every run. It asks once for the
info it should submit (editable later under **User info...**) and can run on a schedule
(**Schedules**). Profiles can also be created up front in **Profiles**.

### 5. Headless / from another program

```bash
python -m ecogent --type analysis "Search Google Scholar for browser agent papers and summarize to md"
python -m ecogent --chat <chat_id> "now export it as docx"     # follow-up in an existing chat
```

Prints a JSON result (chat id, status, output file, token usage). Other agents can call
`ecogent.integration.run_tool_call(...)` with the `TOOL_SCHEMA` (task type + intent).

### Measure the token cost

```bash
python bench/benchmark.py --tasks bench/tasks.example.json --runs 5 --mode cached  --price-in 0.15 --price-out 0.60
python bench/benchmark.py --tasks bench/tasks.example.json --runs 5 --mode nocache --price-in 0.15 --price-out 0.60
```

Uses the LLM from Settings and writes tokens, cached tokens and USD per run to `bench/results.csv`
(`nocache` = every run is a new chat with no reuse: the baseline). Cost limits live in
`ecogent_data/settings.json`: `max_run_tokens` (asks before a run goes over, default 150000),
`max_heals_per_run` (default 6), `max_heal_attempts` (per step, default 2).

### Troubleshooting

- **"Port ... is in use"** - change *Debug port* in Settings or close the other browser instance.
- **No browser found** - set *Browser executable* in Settings or run `python -m playwright install chromium`.
- **LLM error** - check provider, base URL, model name and API key in Settings; the log panel shows the HTTP error.

## Task types

| Type | What happens |
|---|---|
| Analysis | Visit sources, save page text to the temp folder, LLM writes md/docx/json/csv/xlsx |
| Data Scrap | LLM builds a CSS "programmatic pattern" once, sample is validated by LLM and you, then every page is scraped without LLM calls |
| Automation | Log in once in a saved browser profile, provide your info, run on a schedule; handled items are never repeated |
| Software Test | Not implemented yet |
| Others | General browser task |

## Built-in tools

The LLM plans with tools from a registry (`ecogent/toolbox.py`) and only sees the tools of the
chat's task type.

- **Browser:** open_url, fill, click, press, select_option, scroll, wait, screenshot, download,
  upload, save_session
- **Page data:** get_page_data, collect_links, extract_records
- **Flow:** for_each, ask_user
- **Local files:** list_files, read_file (txt/md/json/csv/xlsx/docx; `as_data` feeds the analysis),
  write_file, append_file, copy_file, move_file, delete_file, make_dir, file_exists
- **Results:** analyze, write_output

File tools work in the chat's **selected folder** (chat bar → **Folder...**), or in its output
folder if none is selected. They can only touch the chat, temp, output and selected folders.

## Files per chat (`ecogent_data/chats/<id>/`)

- `plan.json` - goal, destination, output spec, execution memory (cached selectors, validation elements, scraping pattern), collected data, runs
- `current_task.json` - steps the agent executes (editable in the app)
- `steps.json` - execution log
- `chat.json` - messages, memory summary, token usage

## Code (`ecogent/`)

| Module | Role |
|---|---|
| `core.py` | New chat, first plan, follow-ups (rerun / heal / extend / reanalyze), automation requirements |
| `executor.py` | Runs steps; cached selector (identity-checked) -> alternate locators -> local re-find -> obvious candidate, and only then the LLM (probable elements -> broader area -> page outline); bounded self-healing; per-run token budget; hold for user |
| `scraping.py`, `analysis.py` | Pattern scraping and final analysis |
| `relevance.py` | BM25 relevance filter: only goal-relevant page parts go to the analysis LLM |
| `browser.py` | Wraps [playwright_browser_manager](https://github.com/samratpro/playwright_browser_manager) |
| `page_reader.py` | BeautifulSoup candidates, cleaned page text, repeated blocks |
| `llm.py`, `prompts.py` | Providers (retry/backoff, JSON mode, prompt caching), main/cheap model routing, token accounting incl. cached tokens, system prompts |
| `memory.py` | ChromaDB lookup of similar earlier plans (reuses their selectors) |
| `scheduler.py`, `worker.py`, `bridge.py` | Periodic runs, worker thread, agent <-> GUI requests |
| `integration.py` | Tool-call entry point for other agents (task type + intent) |
| `gui/` | DearPyGui app |
