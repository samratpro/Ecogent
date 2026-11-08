"""
LLM access.

LLMClient talks to one provider over plain HTTP: OpenAI, OpenRouter or any
OpenAI-compatible server (/chat/completions), or Anthropic (/v1/messages).
LLMRouter sends simple jobs (element picking, validation, per-page notes, ...) to the
cheap model when one is configured and everything else to the main model,
and reports token usage for every call so the GUI can show the cost.

Cost guards:
  * retries with backoff on rate limits / overload / network errors, so one hiccup does
    not fail a run (a rerun would pay for all uncached work again)
  * provider JSON mode where supported, free local JSON repair, and a repair round-trip
    that sends only the broken reply (never the original prompt again)
  * the static system prompt is marked cacheable; cached input tokens are reported
  * an optional before_call hook enforces the per-run token budget
"""

from __future__ import annotations

import ast
import json
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .config import OPENAI_STYLE, LLMConfig, Settings


class LLMError(Exception):
    pass


class BudgetExceeded(LLMError):
    """The run's token budget is used up and the user did not allow more."""


@dataclass
class LLMResponse:
    text: str
    input_tokens: int               # all input tokens, cached ones included
    output_tokens: int
    model: str
    provider: str
    cached_input_tokens: int = 0    # part of input_tokens read from the provider's prompt cache
    cache_write_tokens: int = 0     # part of input_tokens written to the cache (Anthropic)


RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
RETRIES = 3


class _HTTPFailure(Exception):
    def __init__(self, message: str, status: int = 0, retry_after: float = 0.0):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _post_once(url: str, body: dict, headers: dict, timeout: int) -> dict:
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
        try:
            retry_after = float(e.headers.get("retry-after") or 0)
        except (TypeError, ValueError, AttributeError):
            retry_after = 0.0
        raise _HTTPFailure(f"HTTP {e.code} from {url}: {detail}", e.code, retry_after) from e
    except urllib.error.URLError as e:
        raise _HTTPFailure(f"Cannot reach {url}: {e.reason}") from e
    except (TimeoutError, ConnectionError) as e:
        raise _HTTPFailure(f"Connection to {url} failed: {e}") from e


def _post(url: str, body: dict, headers: dict, timeout: int, retries: int = RETRIES) -> dict:
    """POST with retries on rate limits, overload and network errors."""
    for attempt in range(retries + 1):
        try:
            return _post_once(url, body, headers, timeout)
        except _HTTPFailure as e:
            retryable = e.status == 0 or e.status in RETRY_STATUS
            if not retryable or attempt == retries:
                raise LLMError(str(e)) from e
            delay = e.retry_after or min(30.0, 2.0 ** attempt + random.random())
            time.sleep(min(delay, 60.0))
    raise LLMError("unreachable")


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._json_mode_ok = True       # set to False when the server rejects response_format

    def complete(self, system: str, messages: list[dict], max_tokens: Optional[int] = None,
                 json_mode: bool = False) -> LLMResponse:
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
                    # The system prompt is static per task type: mark it cacheable. Prompts below
                    # the provider's minimum cacheable length are simply not cached (no error).
                    "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                    "messages": messages,
                },
                {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"},
                cfg.timeout,
            )
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {}) or {}
            read = int(usage.get("cache_read_input_tokens") or 0)
            write = int(usage.get("cache_creation_input_tokens") or 0)
            # Anthropic's input_tokens excludes cache reads/writes: report the full input.
            return LLMResponse(text, int(usage.get("input_tokens") or 0) + read + write,
                               int(usage.get("output_tokens") or 0), cfg.model, "anthropic", read, write)

        if cfg.provider in OPENAI_STYLE:
            if not cfg.base_url:
                raise LLMError("Base URL is empty. Open Settings.")
            body = {
                "model": cfg.model,
                "max_tokens": max_tokens,
                "temperature": cfg.temperature,
                # Static system prompt first: OpenAI-style providers cache long identical prefixes.
                "messages": [{"role": "system", "content": system}, *messages],
            }
            url = f"{cfg.base_url.rstrip('/')}/chat/completions"
            use_json = json_mode and self._json_mode_ok
            if use_json:
                body["response_format"] = {"type": "json_object"}
            try:
                data = _post(url, body, _headers(cfg), cfg.timeout)
            except LLMError as e:
                if not use_json or not re.search(r"HTTP 4(00|22)", str(e)):
                    raise
                # This server does not support JSON mode: remember it and retry without.
                self._json_mode_ok = False
                body.pop("response_format", None)
                data = _post(url, body, _headers(cfg), cfg.timeout)
            try:
                text = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as e:
                raise LLMError(f"Unexpected response: {str(data)[:300]}") from e
            usage = data.get("usage") or {}
            cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
            return LLMResponse(text, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
                               cfg.model, cfg.provider, cached)

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
    """Parse JSON from an LLM reply (tolerates code fences, prose, single quotes, trailing
    commas, Python literals and replies cut off by max_tokens)."""
    if text is None:
        raise ValueError("empty reply")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    balanced = _first_balanced(cleaned)
    for candidate in (cleaned, balanced, _repair(balanced or _from_first_bracket(cleaned))):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        try:
            return ast.literal_eval(candidate)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            pass
    raise ValueError(f"no valid JSON in reply: {text[:200]!r}")


def _from_first_bracket(text: str) -> str:
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    return text[start:] if start >= 0 else ""


def _repair(text: str) -> str:
    """Free fixes for common LLM JSON slips: trailing commas, Python literals, and a reply
    cut off mid-way (an unclosed string and open brackets are closed)."""
    if not text:
        return ""
    t = re.sub(r",\s*([}\]])", r"\1", text)
    t = re.sub(r"\bTrue\b", "true", t)
    t = re.sub(r"\bFalse\b", "false", t)
    t = re.sub(r"\bNone\b", "null", t)
    stack: list[str] = []
    in_str = esc = False
    for ch in t:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    if in_str:
        t += '"'
    t = t.rstrip()
    t = re.sub(r",\s*$", "", t)
    t = re.sub(r':\s*$', ": null", t)
    return t + "".join(reversed(stack))


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

REPAIR_PROMPT = """You fix broken JSON. You get the expected format and a reply that is not valid JSON.
Return ONLY the corrected JSON with the same content. No prose, no code fences."""


class LLMRouter:
    def __init__(self, settings: Settings, on_usage: Optional[UsageCallback] = None,
                 log: Optional[Callable[[str], None]] = None):
        self.settings = settings
        self.main = LLMClient(settings.main_llm)
        self.cheap = LLMClient(settings.cheap_llm) if settings.cheap_llm.enabled else None
        self.on_usage = on_usage
        self.log = log
        # Called before every call with the purpose; may raise BudgetExceeded (set per run).
        self.before_call: Optional[Callable[[str], None]] = None

    def _client_for(self, purpose: str) -> LLMClient:
        if self.cheap and purpose in self.settings.cheap_purposes:
            return self.cheap
        return self.main

    def ask(self, purpose: str, system: str, user: str, max_tokens: Optional[int] = None,
            history: Optional[list[dict]] = None, json_mode: bool = False) -> str:
        if self.before_call:
            self.before_call(purpose)
        messages = [*(history or []), {"role": "user", "content": user}]
        client = self._client_for(purpose)
        try:
            resp = client.complete(system, messages, max_tokens, json_mode=json_mode)
        except LLMError as e:
            if client is self.main:
                raise
            # Cheap model failed -> main model. Recorded under its own purpose so this spend
            # is visible in the usage breakdown instead of hiding inside "pick".
            if self.log:
                self.log(f"Cheap model failed for '{purpose}' ({e}); using the main model")
            purpose = f"{purpose}:fallback"
            resp = self.main.complete(system, messages, max_tokens, json_mode=json_mode)
        if self.on_usage:
            self.on_usage(purpose, resp)
        return resp.text

    def ask_json(self, purpose: str, system: str, user: str, max_tokens: Optional[int] = None) -> Any:
        text = self.ask(purpose, system, user, max_tokens, json_mode=True)
        try:
            return extract_json(text)
        except ValueError as e:
            # One cheap repair round-trip: only the broken reply goes back, not the original
            # (possibly 12k-char) prompt.
            if self.log:
                self.log(f"Reply to '{purpose}' was not valid JSON; asking for a repair")
            fixed = self.ask("repair", REPAIR_PROMPT,
                             f"Expected format (end of the original instructions):\n{system[-1500:]}\n\n"
                             f"Broken reply ({e}):\n{text[:6000]}",
                             max_tokens, json_mode=True)
            return extract_json(fixed)
