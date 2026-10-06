# 💻 GitHub / Open Source Projects — Browser Agents & Caching
> **Prepared for:** Ecogent Paper (Samrat)  
> **Date:** October 2026  

---

## 🛠️ Category 1: Open Source Web Agent Frameworks

| # | Project | URL | Stars (Est.) |
|---|---|---|---|
| 1 | Agent-E (EmergentAGI) | https://github.com/EmergentAGI/Agent-E | 2K+ |
| 2 | BrowserGym (ServiceNow) | https://github.com/ServiceNow/BrowserGym | 1.5K+ |
| 3 | Skyvern | https://github.com/Skyvern-AI/skyvern | 6K+ |
| 4 | OpenDevin / OpenHands | https://github.com/All-Hands-AI/OpenHands | 30K+ |
| 5 | AutoGPT | https://github.com/Significant-Gravitas/AutoGPT | 160K+ |
| 6 | LaVague | https://github.com/lavague-ai/LaVague | 4K+ |

### Project Details:

**1. Agent-E** (https://github.com/EmergentAGI/Agent-E)
**Core Focus/Gap:** A highly modular open-source web agent focused on DOM distillation and semantic planning. It addresses the issue of passing massive HTML structures to LLMs.
**Methodology:** Uses a hierarchical architecture. A planner model makes high-level decisions, and a navigator model translates these into Playwright actions on a distilled DOM.
**Relevance to Ecogent:** Agent-E distills the DOM to reduce tokens per step. Ecogent takes this further by entirely skipping the LLM planner phase for cached tasks, executing pre-recorded Playwright actions.

**2. BrowserGym** (https://github.com/ServiceNow/BrowserGym)
**Core Focus/Gap:** An environment for training and evaluating web agents, addressing the lack of standardized tooling across different web agent papers.
**Methodology:** Wraps Playwright in an OpenAI-Gymnasium interface, providing standardized state observations (DOM, accessibility tree, screenshots) and action spaces.
**Relevance to Ecogent:** BrowserGym is the ideal testing ground. Ecogent's architecture (memory + local execution) should ideally be evaluated by running it inside the BrowserGym environment.

**3. Skyvern** (https://github.com/Skyvern-AI/skyvern)
**Core Focus/Gap:** Open-source platform for automating browser workflows using LLMs, specifically targeting complex, multi-step B2B workflows (like filling out insurance forms).
**Methodology:** Uses computer vision and LLMs to understand the visual layout of a page, rather than relying on brittle HTML DOM selectors that change often.
**Relevance to Ecogent:** Skyvern uses expensive VLM calls for robustness. Ecogent achieves speed and low cost by using verified DOM selectors from its JSON cache, falling back to heavy models only on layout changes.

**4. OpenHands (formerly OpenDevin)** (https://github.com/All-Hands-AI/OpenHands)
**Core Focus/Gap:** Generalist software engineering agent that also features extensive web browsing capabilities to read documentation and test web apps.
**Methodology:** Uses a sandboxed Docker environment to execute code and control a headless browser simultaneously, leveraging large context windows.
**Relevance to Ecogent:** Primarily a coding agent, but its browser plugin operates similarly to standard zero-shot planners. It lacks Ecogent's explicit VectorDB workflow caching mechanism.

**5. AutoGPT** (https://github.com/Significant-Gravitas/AutoGPT)
**Core Focus/Gap:** One of the original autonomous agent frameworks. Attempts to achieve high-level goals via web search and basic browser control.
**Methodology:** ReAct prompting loop with a variety of tools (Selenium/Playwright, file search). Highly prone to infinite loops and high API costs on complex tasks.
**Relevance to Ecogent:** AutoGPT represents the "expensive, brute-force" approach to agents. Ecogent solves AutoGPT's cost and looping problems by enforcing strict workflow reuse.

**6. LaVague** (https://github.com/lavague-ai/LaVague)
**Core Focus/Gap:** Large Action Model framework for web automation. Translates natural language into Playwright/Selenium code.
**Methodology:** Uses a dual-model approach: a heavy LLM to plan, and a smaller, faster model (like Llama-3) to generate the exact locator code.
**Relevance to Ecogent:** Similar in using smaller models for execution, but LaVague still generates code dynamically. Ecogent retrieves and executes *pre-validated* JSON blocks, ensuring higher reliability.

---

## 🧠 Category 2: Memory & Caching Systems

| # | Project | URL | Stars (Est.) |
|---|---|---|---|
| 7 | Mem0 (Mem0AI) | https://github.com/mem0ai/mem0 | 20K+ |
| 8 | GPTCache (Zilliz) | https://github.com/zilliztech/GPTCache | 7K+ |
| 9 | Chroma (ChromaDB) | https://github.com/chroma-core/chroma | 13K+ |
| 10 | LangGraph (LangChain) | https://github.com/langchain-ai/langgraph | 10K+ |

### Project Details:

**7. Mem0** (https://github.com/mem0ai/mem0)
**Core Focus/Gap:** Provides a universal memory layer for LLM agents to remember user preferences and facts across sessions.
**Methodology:** Extracts entities and relationships from conversations, storing them in a VectorDB and Neo4j graph database to retrieve relevant context later.
**Relevance to Ecogent:** Mem0 caches *facts*. Ecogent caches *actionable workflows*. While related, Ecogent's memory must store executable steps (clicks, types) rather than just context.

**8. GPTCache** (https://github.com/zilliztech/GPTCache)
**Core Focus/Gap:** Reduces LLM API costs by semantically caching previous responses.
**Methodology:** Embeds user queries. If a new query is semantically similar to an old one, it bypasses the LLM and returns the cached string.
**Relevance to Ecogent:** The exact architectural inspiration for Ecogent. Ecogent is essentially "GPTCache for Browser Agents," returning cached Playwright JSON workflows instead of static text.

**9. Chroma** (https://github.com/chroma-core/chroma)
**Core Focus/Gap:** The open-source embedding database for building AI applications with state and memory.
**Methodology:** Stores embeddings and their metadata, allowing fast nearest-neighbor search for retrieval-augmented generation (RAG).
**Relevance to Ecogent:** The core database technology Ecogent uses to store user intents (e.g., "login to github") and retrieve the corresponding JSON workflows.

**10. LangGraph** (https://github.com/langchain-ai/langgraph)
**Core Focus/Gap:** Framework for building stateful, multi-actor applications with LLMs, using graphs to define agent control flow.
**Methodology:** Defines agents as nodes and edges in a state machine. Allows for cyclic execution (loops) and persistent memory of state.
**Relevance to Ecogent:** Ecogent's overall router logic (VectorDB Check -> Local Execution -> Fallback to Cloud LLM) can be cleanly implemented as a LangGraph state machine.

---

## 🎯 Ecogent vs Open Source Landscape

- **Why Ecogent is necessary:** Existing open-source agents (Agent-E, Skyvern, AutoGPT) focus on **Zero-Shot Task Solving** (figuring out how to do a task from scratch). This is expensive and slow. 
- **The Gap:** There is no open-source web agent explicitly built around the philosophy of **"Solve Once, Cache, and Replay Locally."**
- **Ecogent's Position:** Ecogent bridges the gap between GPTCache (semantic caching) and BrowserGym (web execution) by introducing a stateful, cost-aware workflow retrieval mechanism.
