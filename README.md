# Ecogent

**A Local-First Multi-Agent Architecture for Reducing LLM Costs Through Persistent Tools, Semantic Memory, and Adaptive Model Routing**

---

## Overview

Ecogent is a research-grade experimental CLI prototype that validates whether a local-first multi-agent architecture can significantly reduce LLM API usage, token consumption, and execution overhead — while maintaining high task completion quality.

The core idea: **most agent tasks don't need a cloud LLM on every run.** A local supervisor, semantic tool memory, structured workflow reuse, and a lightweight local model handle the majority of work. The cloud LLM is only called when truly needed — and when it is called, only efficient, filtered context is sent.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    User Input (CLI)                  │
└──────────────────────────┬──────────────────────────┘
                           │
              ┌────────────▼─────────────┐
              │   Local NLP Supervisor    │
              │  - Intent classification  │
              │  - Complexity scoring     │
              │  - Tool/agent routing     │
              └────────────┬─────────────┘
                           │
           ┌───────────────▼────────────────┐
           │   Semantic Memory (ChromaDB)    │
           │  - Tool registry lookup         │
           │  - Browser pattern lookup       │
           │  - Session/project memory       │
           └───────┬───────────────┬────────┘
                   │               │
        ┌──────────▼──┐   ┌────────▼──────────────┐
        │  Local Path │   │     Cloud Escalation   │
        │             │   │  (OpenRouter/OpenAI/   │
        │ Tiny LLM    │   │       Ollama)          │
        │ (135M GGUF) │   └────────┬───────────────┘
        │ + Tools     │            │
        └──────┬──────┘            │
               │                   │
        ┌──────▼───────────────────▼──────┐
        │         Agent Router            │
        │  - os_agent (file/system tasks) │
        │  - browser_agent (web tasks)    │
        │  - [future: code_agent, etc.]   │
        └──────┬──────────────────┬───────┘
               │                  │
   ┌───────────▼──────┐  ┌────────▼───────────────────────┐
   │    OS / Local    │  │       Browser Agent             │
   │    Executor      │  │  ┌──────────────────────────┐   │
   │                  │  │  │  1. Fingerprint task      │   │
   │  - Run tools     │  │  │  2. Lookup saved pattern  │   │
   │  - Generate new  │  │  │     (ChromaDB)            │   │
   │    tools via LLM │  │  │  3a. REPLAY: deterministic│   │
   │  - Verify output │  │  │      Playwright execution  │   │
   └──────────────────┘  │  │  3b. RECORD: LLM-guided   │   │
                         │  │      step-by-step with     │   │
                         │  │      BeautifulSoup DOM     │   │
                         │  │      element extraction    │   │
                         │  │  4. Self-heal on failure   │   │
                         │  │  5. Save pattern for reuse │   │
                         │  └──────────────────────────┘   │
                         └────────────────────────────────┘
```

---

## How It Works

### 1. Local Supervisor (Zero LLM Cost)
Every task first goes through a **local NLP supervisor** — no cloud calls. It handles three main tasks:

- **Intent Classification:** It figures out *what kind* of task you're asking for. For example, it categorizes "visit Amazon and search baby products" as `browser_automation`, but "rename my report.csv file" as an `os_task`.
- **Complexity Scoring:** It decides if a task is simple, moderate, or complex. Simple tasks might be routed to a tiny local model, while complex ones might need the cloud LLM.
- **Agent Routing:** Based on the intent, it forwards the task to the correct specialized agent (e.g., the Browser Agent or the OS Agent) to actually do the work.
- *Under the hood:* Uses TF-IDF + cosine similarity, requiring zero ML model inference for basic routing.

> **🔜 Planned Feature (Dynamic Cloud Model Routing):**
> Another local agent layer will be implemented later that evaluates the exact complexity of the task to decide **which** cloud model to use. For example, routing moderate tasks to a cheaper model (like Llama 3 8B) and saving the expensive models (like GPT-4o or Claude 3.5 Sonnet) only for highly complex tasks.

### 2. Semantic Tool Registry (ChromaDB)
All generated tools and saved browser patterns are stored as semantic embeddings in **ChromaDB**. When a similar task arrives:
- Tools are retrieved by semantic similarity — no LLM needed
- Browser patterns are retrieved by task fingerprint — direct pattern reuse
- **Token cost = 0** for tasks the system has seen before

### 3. Browser Agent — Record & Replay

This is the most sophisticated part of Ecogent. Browser tasks go through a two-phase system:

#### Phase A: Recording (First Run)
```
User Task → LLM plans Step 1 JSON
         → Playwright executes step
         → BeautifulSoup extracts real DOM elements
         → Element map sent back to LLM (not raw HTML)
         → LLM plans Step 2 using actual selectors
         → Repeat until task complete
         → Save entire workflow as BrowserPattern JSON
```

**Key insight:** Instead of dumping raw HTML to the LLM (expensive, noisy), BeautifulSoup extracts a structured **element map**:
```
INPUTS:
  - selector: #search-box  type=text  placeholder='Search...'
BUTTONS:
  - selector: button[aria-label='Search']  text='Search'
PRICES:
  - selector: span.price-amount  text='$29.99'
HEADINGS:
  - <h2> Product Title Here
```
The LLM uses **real selectors** from the live DOM — no guessing.

#### Phase B: Replay (All Future Runs)
```
Same/Similar Task → ChromaDB finds saved pattern (distance ≈ 0)
                 → Execute 7 steps deterministically via Playwright
                 → No LLM calls needed
                 → If a step fails → AI self-healing (one-shot recovery)
```

**Cost model:**
- First run: N cloud LLM calls (one per step)
- Every future run: 0 LLM calls (unless self-healing needed)

#### Self-Healing on Failure
When replay fails (page changed, element moved, timeout), the agent:
1. Captures the current page element map via BeautifulSoup
2. Sends a **one-shot recovery context** to the LLM (just the failure + element map — not the full conversation history)
3. Gets a corrected action
4. Continues replay from that step

This keeps recovery token cost minimal — only the relevant page context is sent, never the accumulated conversation.

### 4. Token Efficiency Design

Several architectural decisions keep token usage low:

| Problem | Solution |
|---|---|
| Raw HTML = huge token cost | BeautifulSoup extracts structured 20-line element map |
| Context bloat on failures | Recovery uses one-shot context, not accumulated history |
| API errors → infinite loops | Explicit `error` flag in provider responses, parse-fail circuit breaker |
| Same task re-runs LLM | ChromaDB pattern reuse, 0 LLM calls on replay |
| LLM outputs markdown/prose | System prompt enforces raw JSON only |

### 5. Variable Extraction & Pattern Reuse
Tasks with the same **intent** but different **parameters** reuse the same saved pattern:

```
"show me the first product price"   → {nth: 1}  ─┐
"show me the second product price"  → {nth: 2}  ──┼─ same pattern, different variable
"what's the third item cost?"       → {nth: 3}  ─┘
```

Ordinal words (first/second/third) are normalized to `{nth}` during fingerprinting. The actual value is extracted and passed as a runtime variable to the pattern.

---

## Project Structure

```
ecogent/
├── ecogent_experiment/
│   ├── cli.py                    # Interactive terminal (menu, chat, config)
│   ├── supervisor.py             # Local NLP supervisor (intent + complexity)
│   ├── router.py                 # Task → agent routing
│   ├── agent.py                  # Main agent orchestrator
│   ├── local_executor.py         # OS/file task execution
│   ├── tool_registry.py          # ChromaDB tool registry + semantic search
│   ├── tool_generator.py         # Cloud LLM generates new Python tools
│   ├── workflow.py               # JSON workflow plan engine
│   ├── db.py                     # Project/session database (JSON)
│   ├── tiny_llm.py               # Tiny local LLM interface (135M GGUF)
│   ├── inference.py              # llama.cpp GGUF inference engine
│   ├── parser.py                 # JSON/text response parser
│   ├── verifier.py               # Assertion-based output verification
│   ├── token_counter.py          # Token usage tracking
│   ├── metrics.py                # Research metrics
│   ├── context.py                # Execution context manager
│   ├── lc_tools.py               # LangChain tool wrappers
│   │
│   ├── browser_workflow/         # Browser Agent subsystem
│   │   ├── manager.py            # Entry point: route to recorder or replayer
│   │   ├── recorder.py           # First-run: LLM-guided step recording
│   │   ├── replayer.py           # Replay saved patterns deterministically
│   │   ├── playwright_engine.py  # Playwright wrapper + BeautifulSoup DOM parser
│   │   ├── fingerprint.py        # Task → fingerprint + variable extraction
│   │   ├── pattern_store.py      # Save/load BrowserPattern JSON + ChromaDB index
│   │   └── schema.py             # Data models (BrowserStep, BrowserPattern, etc.)
│   │
│   ├── agents/                   # Specialized agent implementations
│   └── providers/                # Cloud LLM providers
│       ├── cloud.py              # OpenAI / OpenRouter / Ollama providers
│       └── mock_cloud.py         # Mock provider for testing
│
├── tools/
│   ├── builtin/                  # Permanent built-in tools (file, system, etc.)
│   └── generated/                # Dynamically created tools (per project)
│
├── config/
│   └── config.json               # Provider keys, model paths, thresholds
│
├── data/
│   └── chroma/                   # ChromaDB persistent storage
│
├── projects/                     # Per-session project data + browser patterns
├── models/                       # Local GGUF model files
├── runtime/                      # llama.cpp binary
├── results/                      # Benchmark and experiment results
├── benchmark/                    # Benchmark task definitions
└── tests/                        # Test suite
```

---

## Planned Agents (Roadmap)

The agent routing architecture is designed to plug in new specialist agents:

| Agent | Status | Description |
|---|---|---|
| `browser_agent` | ✅ Implemented | Web automation with record/replay + self-healing |
| `os_agent` | ✅ Implemented | File system, terminal, OS-level tasks |
| `code_agent` | 🔜 Planned | Code writing, bug fixing, debugging |
| `data_agent` | 🔜 Planned | CSV/Excel processing, data analysis |
| `api_agent` | 🔜 Planned | REST API calls, webhook handling |

---

## Quick Start

### Prerequisites
- Python 3.10+
- Playwright browsers: `playwright install chromium`

### Setup
```bash
python bootstrap.py
```

This will:
- Create a `.venv` virtual environment
- Install all dependencies (`playwright`, `beautifulsoup4`, `chromadb`, etc.)
- Download the llama.cpp runtime and SmolLM2-135M-Instruct model
- Initialize ChromaDB and register built-in tools

### Configure Cloud LLM
Edit `config/config.json`:
```json
"cloud_providers": {
  "default": "openrouter",
  "openrouter": {
    "api_key": "sk-or-v1-...",
    "model": "meta-llama/llama-3.1-70b-instruct"
  },
  "openai": {
    "api_key": "sk-...",
    "model": "gpt-4o"
  },
  "ollama": {
    "api_key": "",
    "model": "llama3",
    "base_url": "http://localhost:11434"
  }
}
```

> **Note:** Use a model with strong JSON output capability. `meta-llama/llama-3.1-70b-instruct` on OpenRouter is recommended.

### Usage
```bash
# Activate venv
.venv\Scripts\activate         # Windows
source .venv/bin/activate      # Linux/macOS

# Start interactive agent terminal
ecogent chat

# Single inference
ecogent infer --prompt "Rename report.csv to final.csv"

# System info
ecogent system-info

# Inspect tools
ecogent inspect-tool rename_file
```

---

## Target Hardware
- 8 GB RAM laptop
- CPU only (no GPU required)
- No Ollama, LM Studio, or Docker needed for local mode

---

## Research Hypothesis

> *"Many agent tasks do not require an expensive cloud LLM call on every run. A local supervisor, persistent semantic tool memory, structured workflow reuse, DOM-aware browser automation, and a lightweight local model can handle a significant portion of agent tasks locally — reducing LLM-related cost while maintaining task completion quality."*

---

## License

MIT — Research prototype
