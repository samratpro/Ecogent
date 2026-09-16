"""
Cloud LLM Providers.
"""

import json
import urllib.request
from typing import Any, Dict

WORKFLOW_PROMPT = """
You are an expert planning agent. The user will give you a complex task.
Break the task down into a logical sequence of sub-tasks.
You MUST output ONLY a valid JSON array of objects. Do not include markdown blocks or any other text.
Each object must represent a sub-task and strictly conform to this structure:
{{
  "task_title": "Short descriptive title",
  "execution_tier": "local",
  "agent": "os_agent",
  "tool": null
}}

Task: {task}
"""


class CloudLLMProvider:
    """Base class for cloud LLM escalation providers."""

    def __init__(self, api_key: str = "", model_name: str = "default-model", base_url: str = ""):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url

    def generate_plan(self, task: str) -> Dict[str, Any]:
        raise NotImplementedError

    def generate_workflow_tree(self, task: str) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
        """Generate a structured JSON workflow tree and return (tree, raw_response)."""
        raise NotImplementedError

    def verify(self) -> tuple[bool, str]:
        """Verify configuration and connection. Returns (success, error_msg)."""
        return True, ""


class OpenAIProvider(CloudLLMProvider):
    def __init__(self, api_key: str, model_name: str = "gpt-4o"):
        super().__init__(api_key, model_name, "https://api.openai.com/v1/chat/completions")

    def verify(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "API key is missing."
        return True, ""

    def generate_plan(self, task: str) -> Dict[str, Any]:
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": task}]
        }
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                return {
                    "answer": result["choices"][0]["message"]["content"],
                    "input_tokens": result.get("usage", {}).get("prompt_tokens", 0),
                    "output_tokens": result.get("usage", {}).get("completion_tokens", 0),
                    "model": self.model_name
                }
        except Exception as e:
            return {"answer": f"Error calling OpenAI API: {e}", "input_tokens": 0, "output_tokens": 0, "model": self.model_name}

    def generate_workflow_tree(self, task: str) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
        prompt = WORKFLOW_PROMPT.format(task=task)
        res = self.generate_plan(prompt)
        try:
            from ecogent_experiment.parser import extract_json
            parsed = extract_json(res["answer"])
            if isinstance(parsed, list):
                return parsed, res
            elif isinstance(parsed, dict) and "project_tree" in parsed:
                return parsed["project_tree"], res
        except Exception:
            pass
        # Fallback to single node if parsing fails
        return [{"task_title": task, "execution_tier": "local", "agent": "os_agent", "tool": None}], res


class OpenRouterProvider(CloudLLMProvider):
    def __init__(self, api_key: str, model_name: str = "meta-llama/llama-3-70b-instruct"):
        super().__init__(api_key, model_name, "https://openrouter.ai/api/v1/chat/completions")

    def verify(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "API key is missing."
        return True, ""

    def generate_plan(self, task: str) -> Dict[str, Any]:
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": task}]
        }
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/ecogent",
                "X-Title": "Ecogent"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                return {
                    "answer": result["choices"][0]["message"]["content"],
                    "input_tokens": result.get("usage", {}).get("prompt_tokens", 0),
                    "output_tokens": result.get("usage", {}).get("completion_tokens", 0),
                    "model": self.model_name
                }
        except Exception as e:
            return {"answer": f"Error calling OpenRouter API: {e}", "input_tokens": 0, "output_tokens": 0, "model": self.model_name}

    def generate_workflow_tree(self, task: str) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
        prompt = WORKFLOW_PROMPT.format(task=task)
        res = self.generate_plan(prompt)
        try:
            from ecogent_experiment.parser import extract_json
            parsed = extract_json(res["answer"])
            if isinstance(parsed, list):
                return parsed, res
            elif isinstance(parsed, dict) and "project_tree" in parsed:
                return parsed["project_tree"], res
        except Exception:
            pass
        return [{"task_title": task, "execution_tier": "local", "agent": "os_agent", "tool": None}], res


class OllamaProvider(CloudLLMProvider):
    def __init__(self, api_key: str = "", model_name: str = "llama3", base_url: str = "http://localhost:11434"):
        # API key is typically empty for Ollama
        url = f"{base_url.rstrip('/')}/api/chat"
        super().__init__(api_key, model_name, url)

    def verify(self) -> tuple[bool, str]:
        if not self.base_url:
            return False, "Base URL is missing."
        try:
            # Quick check if Ollama is running
            test_url = self.base_url.replace('/api/chat', '/api/version')
            req = urllib.request.Request(test_url)
            with urllib.request.urlopen(req, timeout=5) as response:
                pass
            return True, ""
        except Exception as e:
            return False, f"Could not connect to Ollama at {self.base_url}: {e}"

    def generate_plan(self, task: str) -> Dict[str, Any]:
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": task}],
            "stream": False
        }
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                return {
                    "answer": result["message"]["content"],
                    "input_tokens": result.get("prompt_eval_count", 0),
                    "output_tokens": result.get("eval_count", 0),
                    "model": self.model_name
                }
        except urllib.error.HTTPError as e:
            try:
                error_body = json.loads(e.read().decode())
                error_msg = error_body.get("error", str(e))
            except Exception:
                error_msg = str(e)
            return {"answer": f"Error calling Ollama API: {error_msg}", "input_tokens": 0, "output_tokens": 0, "model": self.model_name}
        except Exception as e:
            return {"answer": f"Error calling Ollama API: {e}", "input_tokens": 0, "output_tokens": 0, "model": self.model_name}

    def generate_workflow_tree(self, task: str) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
        prompt = WORKFLOW_PROMPT.format(task=task)
        res = self.generate_plan(prompt)
        try:
            from ecogent_experiment.parser import extract_json
            parsed = extract_json(res["answer"])
            if isinstance(parsed, list):
                return parsed, res
            elif isinstance(parsed, dict) and "project_tree" in parsed:
                return parsed["project_tree"], res
        except Exception:
            pass
        return [{"task_title": task, "execution_tier": "local", "agent": "os_agent", "tool": None}], res


def create_cloud_provider(config: dict) -> CloudLLMProvider:
    """Factory to create a cloud provider based on config."""
    cloud_config = config.get("cloud_providers", {})
    provider_type = cloud_config.get("default", "mock")
    
    if provider_type == "mock":
        from ecogent_experiment.providers.mock_cloud import MockCloudProvider
        return MockCloudProvider(simulate_latency_ms=500)
        
    provider_settings = cloud_config.get(provider_type, {})
    if isinstance(provider_settings, str):
        provider_settings = {}
        
    api_key = provider_settings.get("api_key", "")
    model_name = provider_settings.get("model", "")
    base_url = provider_settings.get("base_url", "")
    
    if provider_type == "openai":
        return OpenAIProvider(api_key, model_name or "gpt-4o")
    elif provider_type == "openrouter":
        return OpenRouterProvider(api_key, model_name or "meta-llama/llama-3-70b-instruct")
    elif provider_type == "ollama":
        return OllamaProvider(api_key, model_name or "llama3", base_url or "http://localhost:11434")
    else:
        from ecogent_experiment.providers.mock_cloud import MockCloudProvider
        return MockCloudProvider(simulate_latency_ms=500)
