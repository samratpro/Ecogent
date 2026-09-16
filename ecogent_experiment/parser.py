"""
Robust JSON extraction from model output.

Small language models often wrap JSON in surrounding text, markdown code fences,
or produce malformed JSON. This module extracts structured JSON reliably.
"""

import json
import re
from typing import Any, Optional


def extract_json(text: str) -> Optional[dict]:
    """
    Extract the first valid JSON object from text.

    Handles:
    - Pure JSON strings
    - JSON inside markdown code fences (```json ... ```)
    - JSON embedded in natural language text
    - Nested braces
    - Trailing commas (common model error)

    Args:
        text: Raw model output text.

    Returns:
        Parsed dict if valid JSON found, None otherwise.
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # Strategy 1: Try direct parse (model returned clean JSON)
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from markdown code fences
    fence_pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    fence_matches = re.findall(fence_pattern, text, re.DOTALL)
    for match in reversed(fence_matches):
        try:
            result = json.loads(match.strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find JSON objects using brace matching
    result = _extract_braced_json(text)
    if result is not None:
        return result

    # Strategy 4: Try fixing common errors and retry
    result = _extract_with_fixes(text)
    if result is not None:
        return result

    return None


def _extract_braced_json(text: str) -> Optional[dict]:
    """Extract JSON by finding matched brace pairs."""
    start_indices = [i for i, c in enumerate(text) if c == "{"]

    for start in reversed(start_indices):
        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(text)):
            c = text[i]

            if escape:
                escape = False
                continue

            if c == "\\":
                escape = True
                continue

            if c == '"' and not escape:
                in_string = not in_string
                continue

            if in_string:
                continue

            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        result = json.loads(candidate)
                        if isinstance(result, dict):
                            return result
                    except json.JSONDecodeError:
                        # Try with fixes
                        fixed = _fix_json_string(candidate)
                        try:
                            result = json.loads(fixed)
                            if isinstance(result, dict):
                                return result
                        except json.JSONDecodeError:
                            pass
                    break

    return None


def _fix_json_string(text: str) -> str:
    """Apply common fixes to malformed JSON."""
    # Remove trailing commas before closing braces/brackets
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Fix single quotes to double quotes (simple cases only)
    # Only if no double quotes are present
    if '"' not in text and "'" in text:
        text = text.replace("'", '"')

    # Fix unquoted keys: word: -> "word":
    text = re.sub(r"(\{|,)\s*(\w+)\s*:", r'\1"\2":', text)

    return text


def _extract_with_fixes(text: str) -> Optional[dict]:
    """Try to extract JSON after applying fixes to the entire text."""
    # Find all potential JSON substrings and try to fix them
    pattern = r"\{[^{}]*\}"
    matches = re.findall(pattern, text)

    for match in reversed(matches):
        fixed = _fix_json_string(match)
        try:
            result = json.loads(fixed)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


def validate_decision(data: dict) -> dict:
    """
    Validate and normalize a Tiny LLM decision JSON.

    Ensures required fields exist with sensible defaults.

    Args:
        data: Parsed JSON dict from model output.

    Returns:
        Normalized decision dict with all expected fields.
    """
    normalized = {
        "intent": data.get("intent", "unknown"),
        "complexity": data.get("complexity", "unknown"),
        "tool": data.get("tool", None),
        "execution": data.get("execution", "cloud"),
        "escalate": data.get("escalate", True),
        "confidence": _normalize_confidence(data.get("confidence", 0.0)),
    }

    # Normalize complexity
    valid_complexities = {"simple", "moderate", "complex", "unknown"}
    if normalized["complexity"] not in valid_complexities:
        normalized["complexity"] = "unknown"

    # Normalize execution
    valid_executions = {"local", "cloud", "tiny_llm"}
    if normalized["execution"] not in valid_executions:
        normalized["execution"] = "cloud"

    return normalized


def _normalize_confidence(value: Any) -> float:
    """Normalize confidence to a float between 0 and 1."""
    try:
        conf = float(value)
        return max(0.0, min(1.0, conf))
    except (ValueError, TypeError):
        return 0.0
