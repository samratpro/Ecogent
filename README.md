# Ecogent

**A Local-First Multi-Agent Architecture for Reducing LLM Costs Through Persistent Tools and Adaptive Model Routing**

## Overview

Ecogent is a research-grade experimental CLI prototype that validates whether a local-first multi-agent architecture can reduce unnecessary LLM usage, token consumption, API calls, and execution overhead while maintaining acceptable task completion.

## Architecture

```
User Input
    ↓
Local NLP + ML Supervisor
    ↓
Local Tool / Semantic Memory Retrieval (Chroma)
    ↓
Local Tiny LLM Fallback (SmolLM2-135M)
    ↓
Specialized Agent Selection
    ↓
JSON Workflow / Project Tree
    ↓
Tool Execution
    ↓
Verification
    ↓
If local capability fails:
    ↓
Cloud LLM (via LangGraph, optional)
```

## Quick Start

### Prerequisites

- Python 3.10+
- Internet connection (for first-time setup)

### Setup

```bash
python bootstrap.py
```

This single command will:
- Create a Python virtual environment
- Install all dependencies
- Download the llama.cpp runtime
- Download the SmolLM2-135M-Instruct model
- Initialize Chroma semantic memory
- Register built-in tools
- Run health checks

### Usage

```bash
# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# System information
ecogent system-info

# Run a single inference
ecogent infer --prompt "Rename report.csv to final.csv"

# Start interactive agent terminal
ecogent chat

# Configure Cloud API Providers
ecogent config list
ecogent config set-provider openrouter --api-key YOUR_KEY
ecogent config use openrouter

# Run benchmark
ecogent benchmark --mode baseline
ecogent benchmark --mode ecogent

# Compare results
ecogent benchmark --compare

# Inspect tools
ecogent inspect-tool rename_file

# Inspect workflow
ecogent inspect-workflow
```

## LLM Configuration

Ecogent supports running with local models (via Ollama or llama.cpp) as well as cloud-based LLMs (OpenAI, OpenRouter) as fallbacks when local execution is insufficient.

> **⚠️ Important Note:** When selecting a Cloud LLM provider and model (especially on OpenRouter or Ollama), **ensure that you choose a model with strong tool-calling and JSON-formatting capabilities** (e.g., GPT-4o, Claude 3.5 Sonnet, Llama-3-70B-Instruct). The system relies heavily on the Cloud LLM to write Python tool scripts and output strict JSON workflow plans.

To configure your LLM providers, you can either use the CLI or manually edit the `config/config.json` file.

### Option 1: Using the CLI

```bash
# List available providers and current configuration
ecogent config list

# Set up OpenRouter
ecogent config set-provider openrouter --api-key "sk-or-v1-..." --model "meta-llama/llama-3-70b-instruct"

# Set up OpenAI
ecogent config set-provider openai --api-key "sk-..." --model "gpt-4o"

# Set up Ollama (Local)
ecogent config set-provider ollama --base-url "http://localhost:11434" --model "llama3"

# Choose the active default provider
ecogent config use openrouter
```

### Option 2: Editing config.json

Open `config/config.json` and update the `cloud_providers` section. Replace the `"see README.md"` strings with your configuration object:

```json
  "cloud_providers": {
    "default": "openrouter",
    "openrouter": {
      "api_key": "sk-or-v1-...",
      "model": "meta-llama/llama-3-70b-instruct"
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

## User Manual

The core of Ecogent is the interactive agent terminal. Start it by running:
```bash
ecogent chat
```

### 1. Starting a New Session
When you start a new session and submit a complex task, the Ecogent system triggers its **Proactive Workflow Engine**:
1. **Memory Search**: It checks the Chroma Vector DB (`workflow_memory`) to see if a similar task has been solved before. If it finds a match, it reuses the plan to save API costs.
2. **Plan Generation**: If no match is found, it falls back to the Cloud LLM to generate a strict JSON `plan.json` containing step-by-step sub-tasks.
3. **Autonomous Execution**: The system iterates through the plan. For each step, it attempts to find an existing Local Semantic Tool.
4. **Tool Generation**: If no tool exists, it calls the Cloud LLM to write a brand new Python Tool script on the fly.
5. **Verification**: After all steps execute locally, the Cloud LLM verifies the output.

### 2. Loading Existing Sessions
You can resume past chats. The system will display all your projects along with exact **Input / Output Token metrics** so you can easily track API costs and savings.

### 3. Modifying Cloud APIs
You can dynamically swap your fallback Cloud LLM (OpenAI, OpenRouter, Ollama) directly from the CLI's main menu without needing to restart the application.

## Target Hardware

- 8 GB RAM laptop
- CPU only (no GPU required)
- No Ollama, LM Studio, or Docker

## Research Hypothesis

> "Many agent tasks do not require an expensive cloud LLM call. A local supervisor, persistent tools, semantic retrieval, structured workflows, and a lightweight local model can handle a significant portion of tasks locally and therefore reduce LLM-related cost."

## Project Structure

```
ecogent/
├── ecogent_experiment/       # Core Python package
│   ├── cli.py                # CLI entry point
│   ├── supervisor.py         # Local NLP supervisor
│   ├── tiny_llm.py           # Tiny LLM interface
│   ├── inference.py          # GGUF inference engine
│   ├── router.py             # Execution router
│   ├── parser.py             # JSON response parser
│   ├── verifier.py           # Assertion-based verification
│   ├── workflow.py           # JSON workflow engine
│   ├── tool_registry.py      # Chroma tool registry
│   ├── metrics.py            # Research metrics calculator
│   ├── agents/               # Specialized agents
│   └── providers/            # Cloud LLM providers
├── tools/                    # Tool implementations
│   ├── builtin/              # Permanent built-in tools
│   └── generated/            # Dynamically created tools
├── benchmark/                # Benchmark task definitions
├── config/                   # Configuration files
├── models/                   # Local model files
├── runtime/                  # llama.cpp runtime
├── results/                  # Experiment results
└── tests/                    # Test suite
```

## License

MIT - Research prototype
