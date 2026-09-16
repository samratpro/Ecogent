"""
Tiny LLM interface.

High-level wrapper around the inference engine that constructs
structured classification prompts and returns validated decisions.

The Tiny LLM is a FALLBACK / DECISION component only:
- Intent classification
- Complexity classification
- Local/cloud routing
- Tool selection assistance
- Workflow verification
- Task completion verification

It does NOT generate long answers, execute commands, or modify files.
It only returns structured JSON decisions.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

from ecogent_experiment.inference import InferenceEngine, InferenceResult
from ecogent_experiment.parser import extract_json, validate_decision


# ============================================================
# Prompt Templates
# ============================================================

CLASSIFICATION_PROMPT = """<|im_start|>system
You are a task classifier for an AI agent system. Your job is to classify user requests.
Respond with a single JSON object. No other text.

Categories:
- intent: file_operation, data_processing, system_info, code_generation, testing, browsing, unknown
- complexity: simple, moderate, complex
- execution: local, cloud
- tool: the tool name if known, null if unknown

JSON format:
{{"intent": "...", "complexity": "...", "tool": "...", "execution": "...", "escalate": false, "confidence": 0.95}}
<|im_end|>
<|im_start|>user
Classify this task: "{task}"
<|im_end|>
<|im_start|>assistant
"""

TOOL_SELECTION_PROMPT = """<|im_start|>system
You select the best tool for a task. Available tools: {tools}
Output a JSON object with the exact name of the tool you chose. Do not use placeholders.
Example: {{"tool": "actual_tool_name_here", "confidence": 0.95}}
If no available tool can solve the task, use "tool": null.
<|im_end|>
<|im_start|>user
Task: "{task}"
<|im_end|>
<|im_start|>assistant
"""

VERIFICATION_PROMPT = """<|im_start|>system
You verify task completion. Respond with JSON only.
{{"verified": true/false, "reason": "..."}}
<|im_end|>
<|im_start|>user
Task: "{task}"
Result: {result}
Was this task completed successfully?
<|im_end|>
<|im_start|>assistant
"""

ROUTING_PROMPT = """<|im_start|>system
You decide if a task needs cloud LLM or can be handled locally.
Respond with JSON only: {{"route": "local"|"cloud", "reason": "...", "confidence": 0.95}}
<|im_end|>
<|im_start|>user
Task: "{task}"
Available local tools: {tools}
<|im_end|>
<|im_start|>assistant
"""


@dataclass
class TinyLLMDecision:
    """Structured decision from the Tiny LLM."""
    intent: str = "unknown"
    complexity: str = "unknown"
    tool: Optional[str] = None
    execution: str = "cloud"
    escalate: bool = True
    confidence: float = 0.0
    raw_output: str = ""
    json_valid: bool = False
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "complexity": self.complexity,
            "tool": self.tool,
            "execution": self.execution,
            "escalate": self.escalate,
            "confidence": self.confidence,
            "json_valid": self.json_valid,
            "latency_ms": round(self.latency_ms, 2),
        }


class TinyLLM:
    """
    High-level Tiny LLM interface for structured decision-making.

    All interactions produce structured JSON decisions.
    The model never directly executes anything.
    """

    def __init__(self, engine: InferenceEngine):
        """
        Initialize the Tiny LLM interface.

        Args:
            engine: Configured InferenceEngine instance.
        """
        self.engine = engine

    def classify_task(self, task: str) -> TinyLLMDecision:
        """
        Classify a user task into intent, complexity, and routing.

        Args:
            task: The user's request text.

        Returns:
            TinyLLMDecision with classification results.
        """
        prompt = CLASSIFICATION_PROMPT.format(task=task)
        result = self.engine.infer(prompt, max_tokens=128)

        return self._parse_decision(result)

    def select_tool(self, task: str, available_tools: list[str]) -> TinyLLMDecision:
        """
        Select the best tool for a task from available options.

        Args:
            task: The user's request text.
            available_tools: List of available tool names.

        Returns:
            TinyLLMDecision with tool selection.
        """
        tools_str = ", ".join(available_tools)
        prompt = TOOL_SELECTION_PROMPT.format(task=task, tools=tools_str)
        result = self.engine.infer(prompt, max_tokens=64)

        decision = self._parse_decision(result)

        # Extract tool from decision if present
        if decision.json_valid:
            json_data = extract_json(result.output)
            if json_data and "tool" in json_data:
                decision.tool = json_data["tool"]

        return decision

    def verify_completion(self, task: str, result_data: str) -> dict:
        """
        Verify whether a task was completed successfully.

        Args:
            task: The original task description.
            result_data: String representation of the task result.

        Returns:
            Dict with 'verified' (bool) and 'reason' (str).
        """
        prompt = VERIFICATION_PROMPT.format(task=task, result=result_data)
        result = self.engine.infer(prompt, max_tokens=64)

        json_data = extract_json(result.output)
        if json_data:
            self.engine.stats.json_valid_count += 1
            return {
                "verified": json_data.get("verified", False),
                "reason": json_data.get("reason", ""),
            }

        self.engine.stats.json_invalid_count += 1
        return {"verified": False, "reason": "Could not parse verification response"}

    def decide_routing(self, task: str, available_tools: list[str]) -> TinyLLMDecision:
        """
        Decide whether a task should be handled locally or escalated to cloud.

        Args:
            task: The user's request text.
            available_tools: List of available local tool names.

        Returns:
            TinyLLMDecision with routing decision.
        """
        tools_str = ", ".join(available_tools)
        prompt = ROUTING_PROMPT.format(task=task, tools=tools_str)
        result = self.engine.infer(prompt, max_tokens=64)

        decision = self._parse_decision(result)

        # Check route field
        json_data = extract_json(result.output)
        if json_data and "route" in json_data:
            route = json_data["route"]
            decision.execution = route if route in ("local", "cloud") else "cloud"
            decision.escalate = decision.execution == "cloud"

        return decision

    def _parse_decision(self, result: InferenceResult) -> TinyLLMDecision:
        """Parse an inference result into a TinyLLMDecision."""
        decision = TinyLLMDecision(
            raw_output=result.output,
            latency_ms=result.latency_ms,
        )

        if not result.success:
            decision.json_valid = False
            return decision

        json_data = extract_json(result.output)
        if json_data:
            validated = validate_decision(json_data)
            decision.intent = validated["intent"]
            decision.complexity = validated["complexity"]
            decision.tool = validated["tool"]
            decision.execution = validated["execution"]
            decision.escalate = validated["escalate"]
            decision.confidence = validated["confidence"]
            decision.json_valid = True
            self.engine.stats.json_valid_count += 1
        else:
            decision.json_valid = False
            self.engine.stats.json_invalid_count += 1

        return decision

    def get_stats(self) -> dict:
        """Get accumulated inference statistics."""
        return self.engine.stats.to_dict()
