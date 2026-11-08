# Benchmark — What You Have to Do by Hand

> The code for the methodology is done (`bench/drift_bench.py`, `bench/lab/`, `bench/summarize.py`).
> This page is the checklist for the parts only you can do: real LLM runs (your API keys and money),
> watching the browser, testing the other agents by hand, and recording everything for the paper.
> Run every command from the repo root.

---

## 0. Before anything (once)

| # | Do this | Why |
|---|---|---|
| 0.1 | Open the app → **Settings → Main LLM**: provider, API key, model. Press **Test connection**. | The benchmark uses your Settings. |
| 0.2 | **Settings → Cheap model** (optional): provider, key, model (e.g. `gpt-4o-mini`), tick the small jobs. | Main + cheap is the normal Ecogent setup. |
| 0.3 | Write down the **exact model names and today's prices** (input / output / cached, USD per 1M tokens) from the providers' pricing pages, with the date. | Dollar figures in the paper must name model, price and date. |
| 0.4 | Set **Temperature = 0** for both models (Settings → each LLM tab) for the benchmark. | Fewer random differences between runs. Put it back afterwards if you like. |
| 0.5 | Commit your code (`git commit`) before a benchmark session. | The manifest records the git commit; results must match a known code version. |
| 0.6 | Close other Ecogent windows and stray browsers. Turn off VPN / ad-blockers for localhost. | Port 8790 and the debug port must be free; extensions change pages. |

## 1. Free checks (no API cost, ~3 minutes)

```bash
python -m bench.lab.selftest          # must print: 24 tasks {...}  and  LAB OK
python -m bench.lab.fake_run bench/results/fake   # must print: FAKE RUN OK
```
If either fails, stop and fix (or ask) — the real numbers would not be trustworthy.

## 2. Pilot run (small cost, ~30–60 minutes)

Goal: see the curve on a few tasks before paying for the full run, and measure time and cost per run.

```bash
python bench/drift_bench.py --tasks shop_baby_under_30,papers_caching,jobs_python,crm_add_deal \
    --variants ecogent,compile_only,nocache --levels 0,1,2,3,4 --seeds 1,2 \
    --price MAIN_MODEL=IN,OUT,CACHED --price CHEAP_MODEL=IN,OUT,CACHED \
    --interactive --out bench/results/pilot.csv
python bench/summarize.py bench/results/pilot.csv --by-task --out bench/results/pilot_summary.md
```
- Replace `MAIN_MODEL` / `CHEAP_MODEL` with the names as recorded in usage, e.g. `gpt-4o-mini` or
  `anthropic:claude-sonnet-5-5`, and the prices from step 0.3. A warning `no --price for model` means a name
  did not match: fix it and re-run `summarize` (costs are only computed at run time, so re-run the pilot).
- **Watch the browser** for the first few runs. The browser is visible by default; do not click in it.
- `--interactive`: if a run ever needs a person, the terminal asks you; handle it and press Enter.
  On the lab sites this should not happen — note it if it does.

**Look at `pilot_summary.md` and decide:**
1. `ecogent` rerun at level 0 ≈ 0 calls and success ≈ 100%? (must be true)
2. `compile_only` success drops at levels 1–4? (expected)
3. `ecogent` cost at levels 1–4 well below `nocache`, with success staying high? (**this is the paper**)
4. `rerun2` ≈ 0 calls? (repairs are saved)

If 3 is false, tell me before the full run — we look at *which* step costs (column `by_purpose`) first.

## 3. Full run (main comparison)

Size: 24 tasks × 3 seeds; per task and seed `ecogent` 11 runs, `compile_only` 11, `nocache` 6 →
**2,016 runs**. With `--no-rerun2` it is 1,296 runs. Use the pilot's average seconds and dollars per run
to estimate the total before you start. Run it in batches (one task type per session); rows are appended
to the same CSV, so a batch can be repeated after a crash (delete that batch's rows first).

```bash
python bench/drift_bench.py --tasks shop_baby_under_30,shop_books_rated,shop_toys_under_20,shop_books_all,shop_search_mini,crm_customers,crm_all_contacts,crm_big_deals \
    --variants ecogent,compile_only,nocache --levels 0,1,2,3,4 --seeds 1,2,3 \
    --price ... --price ... --interactive --out bench/results/main.csv
# then the 7 analysis tasks, then the 9 automation tasks (python -m bench.lab.selftest lists all names)
python bench/summarize.py bench/results/main.csv --by-task --out bench/results/main_summary.md
python bench/plot.py bench/results/main.csv --out bench/results/figures
```
- **Repeats (LLM randomness):** add `--repeats 2` (or 3) on at least a subset of tasks. Seeds change the site
  changes; repeats run the *same* pages again with a fresh agent, so the paper can separate "the model was
  random" from "the site changed". Costs ×repeats.
- **`main_summary.md`** now has three parts: (1) the table per system × level × phase with 95% confidence
  intervals, (2) **paired tests** Ecogent vs each baseline (Wilcoxon on cost, exact binomial on success;
  p < 0.05 = real difference), (3) **total cost of ownership** and the **break-even run** against "no reuse".
- **Figures** (`bench/results/figures/*.svg`): fig1 cost per rerun vs drift level, fig2 success vs drift level,
  fig3 cumulative cost (break-even), fig4 ablations (after step 4). SVG goes straight into LaTeX via
  `\includesvg` or convert to PDF with Inkscape.

## 4. Ablations (which part of the ladder saves what)

On a subset (e.g. 8 tasks: 3 scraping, 2 analysis, 3 automation), 3 seeds:
```bash
python bench/drift_bench.py --tasks <8 task names> \
    --variants ecogent,no_identity,no_alternates,no_refind,no_obvious,no_graded,no_cheap \
    --levels 0,1,2,3,4 --seeds 1,2,3 --price ... --price ... --interactive --out bench/results/ablations.csv
```
`no_identity` is the "blind replay" check: expect *wrong* elements to be used (success drops or precision
drops) rather than higher cost.

## 5. Other agents, by hand (success rate and time only)

Agents you cannot script or meter (Claude in Chrome, Perplexity Comet, Antigravity browser agent, ChatGPT
agent if it can reach localhost) are tested with the console:
```bash
python -m bench.lab.serve --system "claude-in-chrome" --level 0 --seed 1
> start jobs_python          # resets the site and prints the exact prompt to paste into the agent
> score                      # automation: scored from what the site recorded
> start papers_caching
> score C:\path\to\report.md   # scraping / analysis: give the file the agent produced
> level 2                     # then repeat the same tasks at another drift level
```
Rules for a fair comparison:
- Paste the prompt **exactly** as printed (it already contains the user's name / email when needed).
- One attempt per task and level; do not help the agent. If it asks a question, answer with the facts in the
  prompt only, and write that in the note.
- Use a fresh chat for every attempt. Record the agent's version / model in `--system`
  (e.g. `perplexity-comet-2026-11`).
- Do at least levels 0 and 3 for every task, 1 seed. The console times each attempt.
- **Never** report tokens or dollars for these agents — they are not measurable. Only success, precision,
  recall and time, clearly labelled as "manual, not reproducible".

## 5b. Your real-world study (32 real cases, weekly rounds)

This is the part where **you use every agent yourself, as a normal user**. It shows Ecogent works on real
sites; the lab benchmark (steps 2–4) proves the cost claim. Keep both — neither alone is enough.

- Cases: `bench/real_cases.json` — 32 cases (12 scraping, 8 analysis, 12 automation) on public practice sites
  built for automation (books/quotes.toscrape, scrapethissite, webscraper.io test sites, the-internet,
  saucedemo, practicetestautomation, demoqa) plus Wikipedia and Hacker News for reading tasks. **Before round
  1, open each site once and check its terms / robots.txt still allow this**; drop or replace any that don't.
  Check the pass rules by eye once (site contents can differ from when they were written).
- Log every attempt:
  ```bash
  python bench/real_log.py --system ecogent --round 1
  > start R04 20261115_101500_ab12     # Ecogent: give the chat id so its tokens are counted
  > score 1 0                          # 1 / 0.5 / 0 by the pass rule, then how many times you stepped in
  python bench/real_log.py --system claude-in-chrome-2026-11 --round 1
  > start R04
  > score 0.5 1
  ```
- **Rounds:** run all 32 cases with every system in week 1, then **repeat the same cases in weeks 2, 3, 4**.
  For Ecogent, week 2+ uses **Run again** on the week-1 chat (that is the point: reuse under natural site
  change); the other agents start fresh each time (they have no reuse).
- What to report from it: score per system per round, helps per case, seconds; for Ecogent also LLM calls and
  tokens per round (expect week 1 high, later weeks near zero unless a site changed). If a site visibly changed
  between rounds, write that in the note — those are your natural-drift examples.

## 6. What to keep for the paper

| Keep | Where |
|---|---|
| All CSVs + `*.manifest.json` (args, models, git commit, start time) | `bench/results/` (git-ignored — back it up!) |
| Model names, prices, price date, temperature | write into a `bench/results/NOTES.md` |
| Machine (CPU, RAM, OS), browser (Brave/Chromium version), Python version | `NOTES.md` |
| Anything unusual (a crash, a captcha, a manual answer) with the CSV row time | `NOTES.md` |
| Summaries (`summarize.py --by-task --out ...`) | `bench/results/*_summary.md` |

## 7. Pitfalls

- Do not change code between batches of the same experiment (or start a new CSV and say so).
- Do not run two benchmarks at once (shared ports and browser).
- A provider outage or rate limit shows up as failed runs with 0 calls — re-run that batch, note it.
- Do not use the lab sites' answers to tune prompts: that would be training on the test set. If you change a
  prompt because of what you saw, re-run **everything** afterwards.
- Keep `ecogent_data/settings.json` private (API keys); never commit `bench/results/`.

## 8. When you send me results

Send `main_summary.md`, the ablations summary, `figures/`, `manual.csv` and `real.csv`. I can then check the
numbers for anything that looks wrong, build the paper tables and help write the results section.
