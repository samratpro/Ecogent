# Ecogent vs Others — Point-to-Point Analysis

> **Status:** working analysis (2026-11-08), written before the benchmark. Every claim about Ecogent
> is checked against the code (file names given). Claims about other systems come from their papers /
> docs (see Sources); proprietary products (Claude app, Antigravity, Perplexity) are described only from
> public behaviour, not internals.
>
> **Scope:** Ecogent is now a **browser-only agent** with two API models (main + cheap). The old plan
> (tiny local LLM supervisor, coding/testing sub-agents) is dropped; older notes that describe it are outdated.

---

## 1. One-paragraph summary

Most browser agents keep the LLM **inside** the loop: observe page → LLM → act → observe → LLM …, on every
step of every run. Recent work moved the LLM **out** of the loop by compiling a task once and replaying it
(Stagehand caching, browser-use workflow-use, Agentic Compilation, AgentRR, plan caching). Ecogent belongs to
this second family, so **"reuse a plan to save tokens" is not new**. What the others leave open is
**what happens when the website changes**: replay systems either break and need a human (Agentic Compilation),
or fall back to a full LLM action (Stagehand self-heal), or have an immature fallback (workflow-use).
Ecogent's distinct idea is **automatic repair whose cost grows with how much the site changed, not with task
length**: verify the remembered element first, then repair through a cheapest-first ladder, heal only the broken
step, write the fix back. That idea is untested at scale; the benchmark has to show it.

---

## 2. The three families of browser agents

| Family | How it works | Cost of run 1 | Cost of run 2..N | When the site changes |
|---|---|---|---|---|
| **A. LLM-in-the-loop (traditional)** — ReAct-style: browser-use, Agent-E, WebVoyager, SeeAct; general agents with browsing (Claude in Chrome / computer use, Antigravity browser agent, Perplexity Comet) | LLM chooses every action from the current observation (DOM, accessibility tree or screenshot) | High: steps × (observation + history) | **Same as run 1** — nothing is reused | Adapts naturally (it re-reads the page anyway), at full cost |
| **B. Compile / cache and replay** — Stagehand cache, workflow-use, Agentic Compilation, AgentRR, Agentic Plan Caching | LLM (or a human demo) produces actions once; later runs replay them | High (compile) | **≈ 0** | Breaks; then human patch, full LLM fallback, or failure |
| **C. Ecogent** — compile once + verified memory + graded repair | LLM plans once; Python executes; LLM only for what Python cannot decide | High (plan + lookups) | **≈ 0** | **Repairs automatically; cost ∝ size of the change** (hypothesis) |

---

## 3. Dimension-by-dimension comparison

| # | Dimension | Traditional (A) | Replay systems (B) | Ecogent (C) — where in code |
|---|---|---|---|---|
| 1 | Where the LLM sits | Inside every step | Outside (after compile) | Outside; called only on a cache miss — `executor.py` `resolve` |
| 2 | What is stored after a run | Chat / trajectory (maybe summarised) | Action list / selectors / JSON blueprint | Plan + per-step element memory (selector, alternates, element identity, page) — `plan.json`, `Executor.MEMORY_FIELDS` |
| 3 | Is a stored element trusted blindly? | n/a | Usually yes (replay the selector) | **No** — accepted only if tag + stable attributes (+ text) match the stored identity — `_try_cached`, `_identity` |
| 4 | What happens on a broken element | LLM re-reads page (normal step) | Fail, human patch, or full LLM action | Ladder: alternates → local re-find (similarity) → obvious single candidate → LLM with 15 → 60 candidates → focused outline → full outline — `resolve`, `_local_refind`, `pr.obvious_choice` |
| 5 | Repair granularity | Whole loop continues | Whole action / whole task | **Only the broken step**; fix saved for the next run — `heal`, `_replace_step`, `_remember` |
| 6 | Bounded fallback when heal fails | Unbounded loop (step limit) | – | ReAct-style rescue, max moves per step and per run; helper moves saved as optional steps — `_rescue`, `max_rescue_turns`, `max_rescues_per_run` |
| 7 | Cost guard | Step limit | – | Token budget per run, heal / rescue limits — `_budget_check`, `max_run_tokens`, `max_heals_per_run` |
| 8 | Page given to the LLM | Full DOM / accessibility tree / screenshot (some prune) | – at replay | Compact candidate lines, focused outline, cleaned text; never raw HTML — `page_reader.py` |
| 9 | Task-type policies | One generic loop | One generic replay | Analysis: relevance filter + deliverable cached by source hash; Scraping: induced + validated + user-confirmed pattern, 0-call pagination; Automation: dedupe of handled items, saved login session — `analysis.py`, `relevance.py`, `scraping.py`, `executor.py` |
| 10 | Same request again | New full run | Cache hit if same action key | Exact repeat → no planning call; similar request → patch only — `core._exact_reference`, `prompts.ADAPT_HINT` |
| 11 | Follow-ups ("as docx", "run again") | New LLM turn | – | Handled locally when possible, else a small patch — `core._local_follow_up`, `apply_step_changes` |
| 12 | Model use | One strong model | Usually one | Main + cheap model by job type (pick/validate/notes/classify/repair) — `llm.LLMRouter`, `config.CHEAP_PURPOSES_DEFAULT` |
| 13 | Captcha / login | LLM loops or stops | Breaks | Human solves it (visible browser), persistent profile keeps cookies, auto-checks waited out for free — `NeedsUser`, `_wait_out_blocker`, `default_profile` |
| 14 | Cost visibility | Rarely reported | Rarely per step | Tokens per step / purpose, cached tokens, budget — `steps.json`, `chat.json` |

---

## 4. Point-to-point against each system

### 4.1 browser-use (traditional, open source)
- **What it does:** LLM agent loop over the DOM/screenshot; one LLM call per action.
- **Overlap:** same goal (do browser tasks from natural language), Playwright-based.
- **Difference:** browser-use pays per step on every run; Ecogent pays once, then ≈ 0 until something breaks.
- **Verdict:** primary *baseline* for the "traditional" family. Not a novelty threat.

### 4.2 Agent-E, AutoWebGLM, Mind2Web/MindAct (traditional + context reduction)
- **What they do:** reduce what the LLM sees (DOM distillation, HTML pruning, small model filters elements first).
- **Overlap:** Ecogent's `page_reader` token diet and the 15→60 candidate levels are the same family of idea.
- **Difference:** they shrink each call; Ecogent removes most calls.
- **Verdict:** **prior art** for the token diet — cite, don't claim.

### 4.3 Claude (computer use / Claude in Chrome), Antigravity browser agent, Perplexity Comet (general agents with browsing)
- **What they do (public behaviour):** an LLM drives the browser step by step, often with screenshots; strong at
  one-off, open-ended tasks.
- **Overlap:** same user-level tasks.
- **Difference:** no reuse between runs; each repeat costs the same; no token reporting for consumer apps.
- **Verdict:** valid comparison for **success rate and time**, not for tokens/dollars (not measurable, not
  reproducible). Use the Claude *API* in an agent loop if a measurable "Claude" baseline is needed.

### 4.4 Stagehand (cache + selfHeal) — closest open-source tool
- **What it does:** caches successful actions (selectors) and replays them without the LLM; with `selfHeal`, a
  failed cached action is retried as a normal LLM `act()`.
- **Overlap:** strong — cached replay with LLM fallback.
- **Difference:** Stagehand's fallback is one full LLM action; Ecogent first verifies identity, then tries free
  local repairs (alternates, similarity re-find, obvious candidate) and only then graded LLM views. Ecogent also
  has task-type policies and a run budget.
- **Verdict:** **major prior art**. The difference must be shown with numbers (repair cost per drift level).

### 4.5 browser-use workflow-use
- **What it does:** turns a recorded demo into a deterministic workflow; a broken step falls back to the
  browser-use agent. Its authors call the fallback "currently really bad" and the project early-stage.
- **Overlap:** strong — deterministic replay + agent fallback.
- **Difference:** Ecogent compiles from a natural-language request (no demo needed), verifies elements, repairs in
  graded steps and writes repairs back.
- **Verdict:** prior art; weak competitor on repair quality.

### 4.6 Agentic Compilation (arXiv 2604.09718, 2026) — closest paper
- **What it does:** LLM compiles a web task into a deterministic JSON workflow; a runtime executes it with no model
  calls; argues the "LLM rerun crisis" (cost growing per rerun); reliability raised by **human patching** of the JSON.
- **Overlap:** almost the same premise and the same cost argument.
- **Difference:** Ecogent repairs **automatically**, with bounded and graded cost, and keeps the repair.
- **Verdict:** **the paper reviewers will compare against.** Ecogent's claim must be "automatic, cost-bounded repair
  under drift", never "compile once, run free".

### 4.7 AgentRR — Record & Replay (arXiv 2505.17716)
- **What it does:** records agent experience, replays it on similar tasks with a check function; multi-level
  experience abstraction; largely conceptual.
- **Overlap:** record/replay with checks ≈ Ecogent's stored identity checks.
- **Difference:** Ecogent is a working browser system with element-level verification and repair.
- **Verdict:** prior art for the concept; cite.

### 4.8 Agentic Plan Caching (arXiv 2506.14852), Plan Reuse Mechanism (arXiv 2512.21309)
- **What they do:** cache and adapt plans across similar requests (~50% cost cut reported for APC).
- **Overlap:** Ecogent's exact-repeat / similar-request reuse (`_exact_reference`, `ADAPT_HINT`).
- **Difference:** they are general agent plans; Ecogent reuses element-level execution memory.
- **Verdict:** prior art for plan reuse; cite.

### 4.9 Agent Workflow Memory (AWM), SkillWeaver
- **What they do:** induce reusable workflows/skills (AWM: as guidance in the prompt; SkillWeaver: as synthesized APIs).
- **Overlap:** reuse of procedural knowledge.
- **Difference:** AWM still calls the LLM every step (the workflow is guidance); Ecogent executes without it.
- **Verdict:** related work; AWM-style can be a baseline.

### 4.10 Similo (TOSEM 2023), self-healing test locators (e.g. Healenium)
- **What they do:** web-testing research/tools that re-find an element by a weighted similarity over many attributes.
- **Overlap:** Ecogent's `_local_refind` / `_match_score` is the same idea.
- **Difference:** Ecogent puts it inside an LLM agent as one rung of a cost ladder.
- **Verdict:** **prior art** for local re-find — cite Similo explicitly.

### 4.11 AutoCrawler (arXiv 2404.12753), ScrapeGraphAI
- **What they do:** LLM generates a reusable crawler/scraper from page structure.
- **Overlap:** Ecogent's scraping pattern (induce once, validate, paginate for free).
- **Difference:** Ecogent adds LLM validation + user sample confirmation + fill-rate memory and re-induction on drift.
- **Verdict:** prior art for scraping reuse.

### 4.12 RouteLLM (model routing)
- **Overlap:** Ecogent's main / cheap model by job type.
- **Difference:** Ecogent routes by fixed job type, not a learned router.
- **Verdict:** prior art; a minor engineering choice, not a contribution.

---

## 5. Ecogent mechanisms vs prior art (claim table)

| Ecogent mechanism | Closest prior art | Can it be claimed? |
|---|---|---|
| Plan once, Python executes, reruns ≈ 0 calls | Agentic Compilation, Stagehand cache, workflow-use, APC | **No** (known) |
| Verify a cached element's identity before trusting it | AgentRR check functions; test-automation locator checks | Only as part of the ladder |
| Local similarity re-find | Similo | **No** (cite) |
| Cheapest-first repair ladder ending in graded LLM views | none found for LLM browser agents | **Yes — core** |
| Heal only the broken step, write the fix back | Stagehand selfHeal (no graded steps), Agentic Compilation (human) | **Yes — with the ladder** |
| Bounded ReAct rescue that stores helper moves as optional steps | ReAct; no stored-move equivalent found | Minor supporting point |
| Per-task-type reuse policies (analysis hash cache, scraping pattern, automation dedupe) | AutoCrawler, semantic caching | Weak as a contribution; good as system design |
| Token diet (compact candidates, focused outline) | Agent-E, AutoWebGLM, MindAct | **No** (cite) |
| Main + cheap model | RouteLLM | **No** |
| Human-in-the-loop for captcha/login + persistent profile | common practice | **No** (engineering) |
| Cost measured under controlled site drift | none found | **Yes — measurement contribution** |

---

## 6. The defensible novelty (and its limit)

**Claim:** *For compiled browser workflows, Ecogent repairs breakage automatically through a cost-ordered ladder
(identity check → local repairs → graded LLM views → bounded rescue) and writes the repair back, so the LLM cost of
a rerun scales with how much the site changed, not with task length. We provide a reproducible benchmark that
measures cost and success under controlled site drift.*

**Expected result shape (hypothesis — must be measured):**

| Drift level | Traditional (A) | Replay without repair (B) | Ecogent (C) |
|---|---|---|---|
| 0 — no change | full cost, high success | ≈ 0 cost, high success | ≈ 0 cost, high success |
| 1 — renamed classes / ids | full cost | ≈ 0 cost, **success drops** | ≈ 0 (alternates / re-find) |
| 2 — moved / wrapped elements | full cost | success drops | small (local re-find, obvious pick) |
| 3 — changed labels / text | full cost | success drops | some LLM picks |
| 4 — redesign | full cost | fails | larger, still < (A) |

**The limit:** if Ecogent's repair cost at levels 3–4 approaches the traditional loop, or its success drops like
(B), the novelty disappears. Today the evidence is only the DRIFT tests on a small local site.

---

## 7. Where Ecogent is weaker than others (state these honestly)

1. **Open-ended, one-off tasks:** an LLM-in-the-loop agent adapts better; Ecogent's first run is a plan that may
   need heals. Ecogent pays off on **repeated** tasks.
2. **Visual-only pages** (canvas, images without text, drag-and-drop): Ecogent reads HTML only; vision agents
   (SeeAct, UGround, computer use) handle these better.
3. **Full redesigns:** the ladder ends in LLM lookups; a total redesign costs close to a fresh run.
4. **Dynamic, JS-heavy flows** with no stable attributes: identity checks have less to hold on to.
5. **Captchas:** need a human (by design — Ecogent never bypasses them).

---

## 8. Corrections to older notes in this folder

| Old claim | File | Status now |
|---|---|---|
| "No open-source web agent built around Solve Once, Cache, and Replay" | `github_research.md` | **False** — Stagehand cache, workflow-use |
| "No paper stores DOM-level details (selectors) in reusable workflow JSON for direct execution" | `google_research.md` | **False** — Agentic Compilation, Stagehand, AgentRR |
| "No paper combines VectorDB + JSON validation + local tiny LLM + cost benchmark" | `google_research.md` | Weak "combination" argument; tiny LLM no longer in the design |
| "Ecogent-style architecture: tiny local supervisor → specialised agents" | `research/Traditional_Agent_Works_Doc/traditional_agent_react.md` §20 | Old plan |
| "Tiny Local LLM" in Technology | `how_work.md` | Replaced by main + cheap API models |

---

## 9. What the benchmark must contain to prove Section 6

1. 15–30 tasks (analysis, scraping, automation) on local / self-hosted sites with a **ground-truth checker**.
2. Scripted drift levels 0–4 (same seed for every system).
3. Systems: browser-use; Stagehand cache + selfHeal; replay-without-repair (Agentic-Compilation style);
   Ecogent; Ecogent ablations (no identity check, no local re-find, no obvious pick, no graded LLM, no cheap model).
4. Per run: success / precision / recall, tokens, cached tokens, LLM calls, USD (model + price + date), seconds.
5. N ≥ 5 runs per cell; report mean ± spread.
6. Key figure: rerun cost vs drift level, with success rate beside it.
7. General agents (Claude app, Antigravity, Perplexity): success and time only, labelled as such.

---

## Sources
- Agentic Compilation — https://arxiv.org/abs/2604.09718
- Agentic Plan Caching — https://arxiv.org/pdf/2506.14852
- A Plan Reuse Mechanism for LLM-Driven Agent — https://arxiv.org/pdf/2512.21309
- AgentRR: LLM Agents with Record & Replay — https://arxiv.org/abs/2505.17716
- Stagehand caching docs — https://docs.stagehand.dev/v2/best-practices/caching ; https://browserbase.com/blog/stagehand-caching
- browser-use workflow-use — https://brianlovin.com/hn/44007065 ; https://www.sourcepulse.org/projects/2513677
- Similo — https://arxiv.org/abs/2208.00677
- AutoCrawler — https://arxiv.org/html/2404.12753v1
- SkillWeaver (review) — https://themoonlight.io/review/skillweaver-web-agents-can-self-improve-by-discovering-and-honing-skills
- Agent Workflow Memory — arXiv 2409.07429
- Agent-E — arXiv 2407.13032 ; AutoWebGLM — arXiv 2404.03648 ; Mind2Web — arXiv 2306.06070
- RouteLLM (2024) ; ReAct (Yao et al., 2023)
- Don't Break the Cache (prompt caching evaluation) — https://arxiv.org/pdf/2601.06007
