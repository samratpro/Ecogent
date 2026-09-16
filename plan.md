# CLI Configuration and Interactive Chat Implementation

This plan introduces two new capabilities to the `ecogent` CLI: an interactive terminal loop for task submission and a configuration command to manage cloud LLM providers.

## Proposed Changes

### Configuration Updates
We will add a new `cloud_providers` block to `config.json` that looks like this:
```json
  "cloud_providers": {
    "default": "mock",
    "openrouter": {
      "api_key": "",
      "model": "meta-llama/llama-3-70b-instruct"
    },
    "openai": {
      "api_key": "",
      "model": "gpt-4o"
    },
    "ollama": {
      "api_key": "",
      "model": "llama3",
      "base_url": "http://localhost:11434"
    }
  }
```

### [ecogent_experiment/cli.py](file:///c:/Users/samra/Desktop/Academy/AI%20Agent%20research/Ecogent/ecogent_experiment/cli.py)

#### [MODIFY] `ecogent_experiment/cli.py`
Add two new commands:
1. **`chat`**: A continuous REPL loop (`while True`) that:
   - Takes a user prompt.
   - Initialises the `InferenceEngine` (TinyLLM), `Supervisor`, and `Router`.
   - Classifies the intent.
   - Executes it locally or routes it to the cloud.
   - Prints the result and metrics.

2. **`config` command group**:
   - `ecogent config list`: Lists all configured providers and their active models.
   - `ecogent config set-provider <provider_name> --api-key <key> --model <model> --url <url>`: Sets the API credentials for a specific provider in `config.json`.
   - `ecogent config use <provider_name>`: Sets the `default` cloud provider.

### [ecogent_experiment/providers/cloud.py](file:///c:/Users/samra/Desktop/Academy/AI%20Agent%20research/Ecogent/ecogent_experiment/providers/cloud.py)

#### [MODIFY] `ecogent_experiment/providers/cloud.py`
Currently, the providers are mostly mock stubs. We will:
- Update the base `CloudLLMProvider` to read from the newly configured `config.json` settings.
- We will add standard HTTP wrappers for OpenRouter, OpenAI, and Ollama to map configurations to actual API requests (if you want actual API calls, otherwise they will remain structured stubs ready for production integration).

> [!IMPORTANT] 
> **User Review Required**
> Do you want the OpenAI/OpenRouter integrations to actually perform live HTTP requests in this update, or should they remain as configured stubs for the purpose of the architecture test?

## Verification Plan
### Manual Verification
- Run `ecogent config set-provider openrouter --api-key 123 --model gpt-4` and verify `config.json` updates.
- Run `ecogent config list` to verify visibility.
- Run `ecogent chat` and type a basic command (e.g., `Rename file_a to file_b`) to ensure the agent executes it end-to-end within the CLI loop.