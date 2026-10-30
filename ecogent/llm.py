"""
LLM access.

LLMClient talks to one provider over plain HTTP: OpenAI, OpenRouter, Ollama or any
OpenAI-compatible server (/chat/completions), or Anthropic (/v1/messages).
LLMRouter sends cheap jobs (element picking, intent classification, ...) to the
tiny local model when one is configured and everything else to the main model,
and reports token usage for every call so the GUI can show the cost.
"""

from __future__ import annotations

import ast
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .config import OPENAI_STYLE, LLMConfig, Settings


class LLMError(Exception):
    pass


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str


def _post(url: str, body: dict, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise LLMError(f"HTTP {e.code} from {url}: {detail}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"Cannot reach {url}: {e.reason}") from e


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def complete(self, system: str, messages: list[dict], max_tokens: Optional[int] = None) -> LLMResponse:
        cfg = self.cfg
        max_tokens = max_tokens or cfg.max_tokens
        if cfg.provider == "anthropic":
            base = (cfg.base_url or "https://api.anthropic.com").rstrip("/")
            if "openai.com" in base:
                base = "https://api.anthropic.com"
            data = _post(
                f"{base}/v1/messages",
                {
                    "model": cfg.model,
                    "max_tokens": max_tokens,
                    "temperature": cfg.temperature,
                    "system": system,
                    "messages": messages,
                },
                {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"},
                cfg.timeout,
            )
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
            return LLMResponse(text, usage.get("input_tokens", 0), usage.get("output_tokens", 0), cfg.model, "anthropic")

        if cfg.provider in OPENAI_STYLE:
            if not cfg.base_url:
                raise LLMError("Base URL is empty. Open Settings.")
            data = _post(
                f"{cfg.base_url.rstrip('/')}/chat/completions",
                {
                    "model": cfg.model,
                    "max_tokens": max_tokens,
                    "temperature": cfg.temperature,
                    "messages": [{"role": "system", "content": system}, *messages],
                },
                _headers(cfg),
                cfg.timeout,
            )
            try:
                text = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError) as e:
                raise LLMError(f"Unexpected response: {str(data)[:300]}") from e
            usage = data.get("usage") or {}
            return LLMResponse(text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), cfg.model,
                               cfg.provider)

        raise LLMError(f"LLM provider '{cfg.provider}' is not configured. Open Settings.")

    def list_models(self, timeout: int = 8) -> list[str]:
        """Model ids from GET <base>/models - used by Settings to test the connection."""
        cfg = self.cfg
        if cfg.provider == "anthropic":
            base = (cfg.base_url or "https://api.anthropic.com").rstrip("/")
            url, headers = f"{base}/v1/models", {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"}
        elif cfg.provider in OPENAI_STYLE:
            if not cfg.base_url:
                raise LLMError("Base URL is empty")
            url, headers = f"{cfg.base_url.rstrip('/')}/models", _headers(cfg)
        else:
            raise LLMError("No provider selected")
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise LLMError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Cannot reach {url}: {e.reason}") from e
        items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
        return sorted({(m.get("id") or m.get("name")) if isinstance(m, dict) else str(m) for m in items} - {None})


def _headers(cfg: LLMConfig) -> dict:
    headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
    if cfg.provider == "openrouter":
        headers.update({"HTTP-Referer": "https://github.com/samratpro/ecogent", "X-Title": "Ecogent"})
    return headers


# --------------------------------------------------------------------------- JSON
def extract_json(text: str) -> Any:
    """Parse JSON from an LLM reply (tolerates code fences, prose and single quotes)."""
    if text is None:
        raise ValueError("empty reply")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    for candidate in (cleaned, _first_balanced(cleaned)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        try:
            return ast.literal_eval(candidate)
        except (ValueError, SyntaxError):
            pass
    raise ValueError(f"no valid JSON in reply: {text[:200]!r}")


def _first_balanced(text: str) -> str:
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        return ""
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth, in_str, esc, quote = 0, False, False, ""
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
        elif ch in "\"'":
            in_str, quote = True, ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


# --------------------------------------------------------------------------- router
UsageCallback = Callable[[str, LLMResponse], None]


class LLMRouter:
    def __init__(self, settings: Settings, on_usage: Optional[UsageCallback] = None):
        self.settings = settings
        self.main = LLMClient(settings.main_llm)
        self.local = LLMClient(settings.local_llm) if settings.local_llm.enabled else None
        self.on_usage = on_usage

    def _client_for(self, purpose: str) -> LLMClient:
        if self.local and purpose in self.settings.local_purposes:
            return self.local
        return self.main

    def ask(self, purpose: str, system: str, user: str, max_tokens: Optional[int] = None,
            history: Optional[list[dict]] = None) -> str:
        messages = [*(history or []), {"role": "user", "content": user}]
        client = self._client_for(purpose)
        try:
            resp = client.complete(system, messages, max_tokens)
        except LLMError:
            if client is self.main:
                raise
            resp = self.main.complete(system, messages, max_tokens)  # local model down -> main
        if self.on_usage:
            self.on_usage(purpose, resp)
        return resp.text

    def ask_json(self, purpose: str, system: str, user: str, max_tokens: Optional[int] = None) -> Any:
        text = self.ask(purpose, system, user, max_tokens)
        try:
            return extract_json(text)
        except ValueError as e:
            # One repair round-trip, then give up.
            history = [{"role": "user", "content": user}, {"role": "assistant", "content": text}]
            text = self.ask(purpose, system, f"That reply was not valid JSON ({e}). Return ONLY the JSON, nothing else.",
                            max_tokens, history=history)
            return extract_json(text)
