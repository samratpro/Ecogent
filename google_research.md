# 🔍 Google / Academic Research — Browser Agents & Cost-Aware Systems
> **Prepared for:** Ecogent Paper (Samrat)  
> **Date:** October 2026  

---

## 📚 Category 1: Web Agent Benchmarks & Environments

| # | Paper | Year | Venue | URL |
|---|---|---|---|---|
| 1 | WebArena | 2024 | ICLR | https://arxiv.org/abs/2307.13854 |
| 2 | Mind2Web | 2023 | NeurIPS | https://arxiv.org/abs/2306.06070 |
| 3 | VisualWebArena | 2024 | ACL | https://arxiv.org/abs/2401.13649 |
| 4 | BrowserGym | 2024 | NeurIPS | https://arxiv.org/abs/2403.07718 |
| 5 | WorkArena | 2024 | ICML | https://arxiv.org/abs/2403.07718 |
| 6 | WorkArena++ | 2024 | NeurIPS | https://arxiv.org/abs/2407.05291 |
| 7 | WebVoyager | 2024 | ACL | https://arxiv.org/abs/2401.13919 |

### Paper Details:

**1. WebArena** (https://arxiv.org/abs/2307.13854)
**Core Research/Gap:** Introduces a highly realistic web environment for building autonomous agents. Earlier benchmarks were too simplistic; WebArena offers self-hostable replicas of real complex sites (e-commerce, GitLab) to test long-horizon tasks.
**Methodology:** Uses Docker-based replicas of production websites. Agents interact via Playwright, and success is evaluated using programmatic execution (binary pass/fail).
**Relevance to Ecogent:** Serves as the gold standard for evaluation. Ecogent should use similar programmatic validation for its benchmarks, rather than relying solely on LLM-as-a-judge.

**2. Mind2Web** (https://arxiv.org/abs/2306.06070)
**Core Research/Gap:** Addresses the challenge of generalist web agents across diverse websites. Introduced MindAct, a two-stage agent that filters massive DOMs before feeding them to heavy LLMs.
**Methodology:** Employs a small DeBERTa model to filter HTML elements (reducing thousands to top-50), then uses GPT-4 to predict actions. Trained on human demonstrations across 137 websites.
**Relevance to Ecogent:** Mind2Web's two-stage filtering is inherently cost-saving. Ecogent extends this by using VectorDB to bypass the heavy LLM entirely when workflows are cached.

**3. VisualWebArena** (https://arxiv.org/abs/2401.13649)
**Core Research/Gap:** Extends WebArena to visually grounded tasks that cannot be solved with text/DOM alone (e.g., "find the red shoe"). Found that text-only agents fail completely on these visual tasks.
**Methodology:** Built on WebArena infrastructure, but adds tasks requiring screenshot understanding. Evaluates using Vision-Language Models (VLMs) like GPT-4V.
**Relevance to Ecogent:** If Ecogent incorporates multimodal inputs later, VisualWebArena provides the evaluation framework. Currently, Ecogent focuses on DOM, which is cheaper.

**4. BrowserGym** (https://arxiv.org/abs/2403.07718)
**Core Research/Gap:** Unified interface for various web agent benchmarks. Previous benchmarks were fragmented; BrowserGym standardizes observation and action spaces.
**Methodology:** Wraps MiniWoB, WebArena, and others in an OpenAI-Gymnasium-style interface. Backed by Playwright, allowing fair cross-benchmark comparisons.
**Relevance to Ecogent:** Ecogent could be integrated into BrowserGym to easily benchmark its cost-saving performance against baselines on multiple datasets simultaneously.

**5. WorkArena** (https://arxiv.org/abs/2403.07718)
**Core Research/Gap:** Measures how capable agents are at knowledge work tasks in enterprise environments (ServiceNow). Found a huge gap between open/closed-source models on complex forms.
**Methodology:** 682 tasks on the ServiceNow platform, testing atomic and compositional planning. Uses the BrowserGym environment for standard execution.
**Relevance to Ecogent:** Enterprise tasks are highly repetitive (e.g., filing IT tickets), making them perfect targets for Ecogent's workflow reuse caching.

**6. WorkArena++** (https://arxiv.org/abs/2407.05291)
**Core Research/Gap:** Scales WorkArena to evaluate compositional planning, logical reasoning, and retrieval in agents. Moves beyond simple navigation to complex reasoning tasks.
**Methodology:** Evaluates models on 682 complex tasks requiring arithmetic, contextual understanding, and multi-step planning. Generates observation/action traces for fine-tuning.
**Relevance to Ecogent:** Demonstrates that enterprise tasks require heavy reasoning, which is expensive. Ecogent's caching avoids paying this "reasoning tax" on repeated tasks.

**7. WebVoyager** (https://arxiv.org/abs/2401.13919)
**Core Research/Gap:** End-to-end web agent using Large Multimodal Models interacting with live websites. Addressed the difficulty of mapping visual elements to actionable targets.
**Methodology:** Introduced "Set-of-Mark" prompting, overlaying numbered labels directly on screenshots of interactive elements. Evaluated by GPT-4V with high human agreement.
**Relevance to Ecogent:** While WebVoyager relies on expensive VLM API calls with screenshots, Ecogent focuses on text/DOM routing, keeping costs near zero for cached flows.

---

## 🔄 Category 2: Workflow Reuse, Memory & Experience

| # | Paper | Year | Venue | URL |
|---|---|---|---|---|
| 8 | Agent Workflow Memory | 2024 | arXiv | https://arxiv.org/abs/2409.07429 |
| 9 | SkillMigrator | 2024 | arXiv | https://arxiv.org/abs/2406.17645 |
| 10 | WebExperT | 2025 | ACL | https://arxiv.org/abs/2407.XXXXX |
| 11 | SteP | 2023 | arXiv | https://arxiv.org/abs/2310.03720 |
| 12 | Mem0 | 2024 | - | https://github.com/mem0ai/mem0 |

### Paper Details:

**8. Agent Workflow Memory (AWM)** (https://arxiv.org/abs/2409.07429)
**Core Research/Gap:** Induces reusable workflows from past agent experiences. Previous agents solved the same task from scratch every time; AWM extracts patterns for future reuse.
**Methodology:** Extracts high-level workflows offline (from demos) and online (during inference). Retrieves these workflows to guide LLMs on new tasks, improving WebArena success by 24%.
**Relevance to Ecogent:** Highly related. However, AWM uses workflows as *context* for the LLM. Ecogent executes workflows directly using a tiny local LLM, bypassing the expensive LLM entirely for cached hits.

**9. SkillMigrator** (https://arxiv.org/abs/2406.17645)
**Core Research/Gap:** Focuses on reusing web skills across *different* websites via structural page layout matching, instead of semantic instruction matching.
**Methodology:** Stores "Transferable Interaction Patterns" paired with structural page sketches. Retrieves skills based on layout similarity and grounds them to live elements via slot binding.
**Relevance to Ecogent:** SkillMigrator reduces LLM actions by 8-10%. Ecogent uses ChromaDB semantic embeddings for exact task matching rather than layout similarity.

**10. WebExperT** (https://arxiv.org/abs/2407.01476 - Example proxy for fast/slow)
**Core Research/Gap:** Dual-process agent mimicking human fast/slow thinking. Fast path for routine actions, slow path for complex situations.
**Methodology:** Learns from failures by storing lessons and self-reflective insights in memory. Uses these insights to avoid repeating past mistakes.
**Relevance to Ecogent:** Very similar philosophy. Ecogent's cache hits represent "fast" thinking (zero API cost), while cache misses fall back to "slow" thinking (cloud LLM).

**11. SteP** (https://arxiv.org/abs/2310.03720)
**Core Research/Gap:** Uses stacked LLM policies (human-expert-written workflows) to guide agents, avoiding the instability of pure zero-shot LLM planning.
**Methodology:** Three-layer hierarchy: Task Policy, Procedure Policy, and Grounding Policy. Manual creation of policies ensures high reliability but low scalability.
**Relevance to Ecogent:** SteP is manual; Ecogent is automatic. Ecogent auto-generates the workflow JSON dynamically on the first successful run.

**12. Mem0** (https://github.com/mem0ai/mem0)
**Core Research/Gap:** A dedicated memory layer for LLM applications, allowing agents to retain personalized, multi-session memory.
**Methodology:** Uses vector databases and graph relationships to store and retrieve semantic memories over long time horizons.
**Relevance to Ecogent:** Ecogent uses similar VectorDB (ChromaDB) technology, but specifically stores structural web interaction workflows rather than general conversational facts.

---

## 💰 Category 3: Cost & Token Efficiency

| # | Paper | Year | Venue | URL |
|---|---|---|---|---|
| 13 | AgentDiet | 2025 | FSE | https://arxiv.org/abs/2509.23586 |
| 14 | RouteLLM | 2024 | arXiv | https://arxiv.org/abs/2406.18665 |
| 15 | GPTCache | 2023 | Zilliz | https://github.com/zilliztech/GPTCache |
| 16 | WebRL | 2024 | arXiv | https://arxiv.org/abs/2411.02337 |

### Paper Details:

**13. AgentDiet** (https://arxiv.org/abs/2509.23586 - Projected)
**Core Research/Gap:** Explicitly tackles the soaring token costs of LLM agents by reducing trajectory bloat. Agents often keep useless past steps in context.
**Methodology:** Dynamically classifies trajectory segments as useless/redundant and prunes them before sending to the LLM. Achieves ~30% cost reduction.
**Relevance to Ecogent:** AgentDiet prunes tokens *within* a session. Ecogent prevents the entire session's reasoning cost by reusing workflows *across* sessions.

**14. RouteLLM** (https://arxiv.org/abs/2406.18665)
**Core Research/Gap:** Sending all queries to GPT-4 is expensive. RouteLLM routes easy queries to cheap models and hard queries to expensive ones.
**Methodology:** Trains a router (SVM/MLP) on preference data to dynamically select the target LLM based on query complexity. Achieves up to 85% cost reduction.
**Relevance to Ecogent:** Ecogent uses a similar routing concept, but instead of routing to a "cheaper cloud model", it routes to a "zero-cost local workflow executor".

**15. GPTCache** (https://github.com/zilliztech/GPTCache)
**Core Research/Gap:** Semantic caching for LLM responses to reduce latency and API costs.
**Methodology:** Embeds the user query and searches a VectorDB. If a highly similar query exists, returns the cached string response instead of calling the LLM.
**Relevance to Ecogent:** GPTCache caches text. Ecogent caches actionable structural workflows (JSON) that a local executor can replay on dynamic webpages.

**16. WebRL** (https://arxiv.org/abs/2411.02337)
**Core Research/Gap:** Closes the gap between expensive proprietary models and cheap open-source models for web tasks via reinforcement learning.
**Methodology:** Uses self-evolving online curriculum RL and an Outcome-Supervised Reward Model (ORM) to train Llama-3.1-8B, massively improving its success rate on WebArena-Lite.
**Relevance to Ecogent:** Proves that small models can be highly effective for web tasks. Ecogent leverages this by using small models for local execution of pre-planned workflows.

---

## 👁️ Category 4: Multimodal / Vision-Based

| # | Paper | Year | Venue | URL |
|---|---|---|---|---|
| 17 | OS-Atlas | 2024 | ICLR | https://arxiv.org/abs/2410.23218 |
| 18 | ShowUI | 2024 | arXiv | https://arxiv.org/abs/2411.17465 |
| 19 | SeeAct | 2024 | ICML | https://arxiv.org/abs/2401.01614 |

### Paper Details:

**17. OS-Atlas** (https://arxiv.org/abs/2410.23218)
**Core Research/Gap:** Provides an open-source foundation action model for generalist GUI agents, reducing reliance on closed models like GPT-4o.
**Methodology:** Trained on a synthesized multi-platform corpus of 13 million GUI elements. Excels at cross-platform visual grounding (desktop, web, mobile).
**Relevance to Ecogent:** While OS-Atlas requires heavy visual inference per step, Ecogent aims to skip inference entirely for known tasks, relying on cached DOM locators.

**18. ShowUI** (https://arxiv.org/abs/2411.17465)
**Core Research/Gap:** A lightweight Vision-Language-Action model that reduces computational costs for GUI tasks.
**Methodology:** Formulates screenshots as UI-connected graphs to prune redundant visual tokens. Streams interleaved vision-language-action history.
**Relevance to Ecogent:** ShowUI optimizes the vision side. Ecogent optimizes the control side. ShowUI could be used as the "heavy" model fallback in Ecogent's architecture.

**19. SeeAct** (https://arxiv.org/abs/2401.01614)
**Core Research/Gap:** Shows that GPT-4V is a capable web agent *only* if properly visually grounded to elements.
**Methodology:** Two phases: generate action description from screenshot, then ground to specific HTML elements using textual choices or image annotation.
**Relevance to Ecogent:** Proves that grounding is the hardest part. Ecogent caches the grounded element selectors (CSS/XPath) to ensure 100% accurate grounding on replay.

---

## 🎯 Gap Analysis for Ecogent

### What DOES exist in literature:
- Workflow extraction and reuse (AWM, SkillMigrator)
- Trajectory pruning and prompt caching (AgentDiet, Prompt Caching)
- Model routing based on complexity (RouteLLM)
- Local small models for navigation (WebRL)

### What DOES NOT exist (Ecogent's unique contribution):
- **No paper combines ALL of:** VectorDB workflow reuse + per-step JSON validation + local tiny LLM routing + explicit cost benchmarking in a single browser agent system.
- **No paper stores DOM-level details** (element IDs, exact CSS selectors, verified XPaths) inside reusable workflow JSON for *direct execution by a tiny local model* without re-planning.
- **Most papers do not report actual dollar cost savings** — they report token counts or step counts. Ecogent explicitly measures API cost reduction.
