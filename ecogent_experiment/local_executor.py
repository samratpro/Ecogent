"""
Local-First Execution Engine for Ecogent.

This is the core of the Local-First architecture. It sits BEFORE any cloud
LLM call and routes tasks through this priority chain:

    1. Local Supervisor (rule-based, 0 tokens)
    2. Chroma semantic tool retrieval
    3. Deterministic match → Execute tool → Deterministic verify → ANSWER
    4. Tiny LLM fallback (if uncertain)
    5. Cloud LLM escalation (LAST RESORT)

For simple tasks (web search, file rename, list directory), the entire
execution completes with cloud_llm_calls = 0.
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Result dataclass — tracks every call for research metrics
# ---------------------------------------------------------------------------

@dataclass
class LocalFirstResult:
    """Result of a local-first execution with full research metrics."""
    success: bool = False
    output: Any = None
    error: str = ""

    # Execution path trace (for research analysis)
    execution_path: list = field(default_factory=list)

    # Call counts (for cost comparison)
    cloud_llm_calls: int = 0
    tiny_llm_calls: int = 0
    local_tool_calls: int = 0
    planning_calls: int = 0
    verification_calls: int = 0
    tool_internal_llm_calls: int = 0  # e.g., ask_llm inside web_search

    # Token tracking
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0

    # Routing metadata
    intent: str = ""
    complexity: str = ""
    tool_used: Optional[str] = None
    agent_used: Optional[str] = None
    supervisor_confidence: float = 0.0
    chroma_confidence: float = 0.0
    verification_source: str = ""  # "deterministic", "tiny_llm", "cloud", "none"

    # Did we escalate?
    cloud_escalated: bool = False

    # Browser automation context (passed to cli.py cloud path)
    cloud_escalation_context: Optional[dict] = None

    # Latency
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": str(self.output)[:500] if self.output else None,
            "error": self.error,
            "execution_path": self.execution_path,
            "cloud_llm_calls": self.cloud_llm_calls,
            "tiny_llm_calls": self.tiny_llm_calls,
            "local_tool_calls": self.local_tool_calls,
            "planning_calls": self.planning_calls,
            "verification_calls": self.verification_calls,
            "tool_internal_llm_calls": self.tool_internal_llm_calls,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "intent": self.intent,
            "complexity": self.complexity,
            "tool_used": self.tool_used,
            "agent_used": self.agent_used,
            "supervisor_confidence": self.supervisor_confidence,
            "chroma_confidence": self.chroma_confidence,
            "verification_source": self.verification_source,
            "cloud_escalated": self.cloud_escalated,
            "latency_ms": round(self.latency_ms, 2),
        }


# ---------------------------------------------------------------------------
# Centralized cloud escalation policy
# ---------------------------------------------------------------------------

def should_escalate_to_cloud(
    supervisor_decision,
    chroma_results: list,
    tiny_llm_result=None,
    tool_execution_failed: bool = False,
    alternative_tools_available: bool = False,
) -> tuple[bool, str]:
    """
    Centralized decision: should this task escalate to Cloud LLM?

    Returns:
        (should_escalate: bool, reason: str)

    Policy:
        - Simple + known tool with high confidence → NO
        - Simple + ambiguous → Tiny LLM decides
        - Tiny LLM confident → NO
        - Complex intent → YES
        - No local capability → YES
        - Local tool failure + alternative available → NO (retry locally)
        - Local tool failure + no alternative → YES
    """
    decision = supervisor_decision

    # 1. Complex tasks always escalate
    if decision.complexity == "complex":
        return True, "complex_task"

    # 2. Code generation always escalates
    if decision.intent == "code_generation":
        return True, "code_generation_requires_cloud"

    # 3. Unknown intent with no tool match → escalate
    if decision.intent == "unknown" and not chroma_results:
        return True, "unknown_intent_no_tools"

    # 4. Tool execution failed
    if tool_execution_failed:
        if alternative_tools_available:
            return False, "tool_failed_but_alternatives_available"
        return True, "tool_failed_no_alternatives"

    # 5. High-confidence local match → stay local
    if decision.confidence >= 0.7 and decision.tool:
        return False, "high_confidence_local_match"

    # 6. Chroma found a strong match
    if chroma_results and chroma_results[0].get("distance", 1.0) < 0.4:
        return False, "chroma_strong_match"

    # 7. Tiny LLM was consulted and is confident
    if tiny_llm_result is not None:
        if hasattr(tiny_llm_result, "confidence") and tiny_llm_result.confidence >= 0.7:
            return False, "tiny_llm_confident"
        if hasattr(tiny_llm_result, "escalate") and not tiny_llm_result.escalate:
            return False, "tiny_llm_says_local"

    # 8. Moderate complexity with a known tool → stay local
    if decision.complexity == "moderate" and decision.tool:
        return False, "moderate_with_known_tool"

    # 9. Default: escalate if nothing matched
    if decision.confidence < 0.5 and not chroma_results:
        return True, "low_confidence_no_chroma"

    # 10. If we got here, we have some signal — try local first
    return False, "default_try_local"


# ---------------------------------------------------------------------------
# Deterministic verification
# ---------------------------------------------------------------------------

def deterministic_verify(intent: str, tool_name: str, tool_result: Any) -> dict:
    """
    Deterministic assertion-based verification.

    Uses rule-based checks that require NO LLM calls.
    Returns: {"passed": bool, "method": str, "message": str}
    """
    result_str = str(tool_result) if tool_result is not None else ""

    # Web search / browsing: result must contain actual content
    if intent in ("browsing", "web_search") or tool_name in ("web_search", "browse_website", "browser_scrape"):
        has_content = len(result_str.strip()) > 20
        has_error = result_str.startswith("ERROR:") or result_str.startswith("Tool error")
        if has_content and not has_error:
            return {"passed": True, "method": "RESULT_HAS_CONTENT", "message": "Search returned content"}
        return {"passed": False, "method": "RESULT_HAS_CONTENT", "message": "No meaningful content returned"}

    # File operations: check for success indicators
    if intent == "file_operation" or tool_name in (
        "read_file", "write_file", "list_directory", "create_directory",
        "delete_file", "copy_file", "move_file", "rename_file",
        "search_files", "file_exists",
    ):
        has_error = result_str.startswith("ERROR:") or result_str.startswith("Tool error")
        if not has_error and len(result_str.strip()) > 0:
            return {"passed": True, "method": "NO_ERROR_WITH_OUTPUT", "message": "File operation completed"}
        return {"passed": False, "method": "NO_ERROR_WITH_OUTPUT", "message": f"File operation error: {result_str[:100]}"}

    # Data operations
    if intent == "data_processing" or tool_name in (
        "read_csv", "inspect_csv", "filter_dataframe",
        "calculate_statistics", "save_csv", "json_read", "json_write", "merge_csv",
    ):
        has_error = result_str.startswith("ERROR:") or result_str.startswith("Tool error")
        if not has_error and len(result_str.strip()) > 0:
            return {"passed": True, "method": "NO_ERROR_WITH_OUTPUT", "message": "Data operation completed"}
        return {"passed": False, "method": "NO_ERROR_WITH_OUTPUT", "message": f"Data operation error: {result_str[:100]}"}

    # System info
    if intent == "system_info" or tool_name in ("system_info", "process_info"):
        if len(result_str.strip()) > 10:
            return {"passed": True, "method": "RESULT_HAS_CONTENT", "message": "System info retrieved"}
        return {"passed": False, "method": "RESULT_HAS_CONTENT", "message": "No system info returned"}

    # Shell / testing
    if tool_name in ("run_shell", "run_python_test", "run_python_inline"):
        has_error = result_str.startswith("ERROR:") or result_str.startswith("Tool error")
        if not has_error:
            return {"passed": True, "method": "NO_ERROR", "message": "Command executed"}
        return {"passed": False, "method": "NO_ERROR", "message": f"Execution error: {result_str[:100]}"}

    # Network
    if tool_name in ("ping_host", "check_port_open", "download_file"):
        has_error = result_str.startswith("ERROR:") or result_str.startswith("Tool error")
        if not has_error and len(result_str.strip()) > 0:
            return {"passed": True, "method": "NO_ERROR_WITH_OUTPUT", "message": "Network operation completed"}
        return {"passed": False, "method": "NO_ERROR_WITH_OUTPUT", "message": f"Network error: {result_str[:100]}"}

    # Generic fallback: if there's output and no error prefix, call it a pass
    if len(result_str.strip()) > 5 and not result_str.startswith("ERROR:"):
        return {"passed": True, "method": "GENERIC_HAS_OUTPUT", "message": "Tool returned output"}

    # Cannot determine — needs semantic verification
    return {"passed": None, "method": "INDETERMINATE", "message": "Cannot verify deterministically"}


# ---------------------------------------------------------------------------
# Tool argument extraction from user input
# ---------------------------------------------------------------------------

def _extract_tool_args(user_input: str, tool_name: str, intent: str) -> dict:
    """
    Extract tool arguments from user input using simple regex patterns.
    No LLM required — purely deterministic.
    """
    args = {"task": user_input}

    # Web search: extract query
    if tool_name == "web_search":
        # "search Bing for KKBAU" → query = "KKBAU"
        # "search for best campus" → query = "best campus"
        m = re.search(
            r"(?:search|find|look\s*up|query)(?:\s+(?:on|for|in|with|bing|google|duckduckgo))?\s+(?:for\s+|with\s+)?(.+?)(?:\s+and\s+(?:tell|show|give|list)|$)",
            user_input, re.I
        )
        if m:
            args["query"] = m.group(1).strip()
        else:
            # Fallback: use the whole input as the query
            args["query"] = re.sub(r"(?:search|find|go to)\s+(?:bing|google|web)\s+(?:for|with|and)?\s*", "", user_input, flags=re.I).strip()
            if not args["query"]:
                args["query"] = user_input

    # Browse website: extract URL
    elif tool_name in ("browse_website", "browser_scrape"):
        m = re.search(r"(https?://\S+)", user_input)
        if m:
            args["url"] = m.group(1)
        else:
            args["url"] = user_input

    # File operations: extract paths
    elif tool_name in ("read_file", "delete_file", "file_exists"):
        # Try to find a filename/path
        m = re.search(r"['\"]?([A-Za-z0-9_./-]+\.\w+)['\"]?", user_input)
        if m:
            args["path"] = m.group(1)

    elif tool_name == "rename_file" or tool_name == "move_file":
        # "rename report.csv to final_report.csv"
        m = re.search(r"['\"]?([A-Za-z0-9_./-]+\.\w+)['\"]?\s+(?:to|as|into)\s+['\"]?([A-Za-z0-9_./-]+\.\w+)['\"]?", user_input, re.I)
        if m:
            args["source"] = m.group(1)
            args["destination"] = m.group(2)

    elif tool_name == "list_directory":
        m = re.search(r"(?:in|of|at|from)\s+['\"]?([A-Za-z0-9_./-]+)['\"]?", user_input, re.I)
        if m:
            args["path"] = m.group(1)
        else:
            args["path"] = "."

    elif tool_name == "create_directory":
        m = re.search(r"(?:create|make|mkdir)\s+(?:a\s+)?(?:director|folder)y?\s+(?:named?\s+|called\s+)?['\"]?([A-Za-z0-9_./-]+)['\"]?", user_input, re.I)
        if m:
            args["path"] = m.group(1)

    elif tool_name == "search_files":
        m = re.search(r"(?:search|find|look\s+for)\s+['\"]?(.+?)['\"]?\s+(?:in|from|at)\s+['\"]?([A-Za-z0-9_./-]+)['\"]?", user_input, re.I)
        if m:
            args["pattern"] = m.group(1)
            args["directory"] = m.group(2)

    return args


# ---------------------------------------------------------------------------
# Browser task heuristic detector
# ---------------------------------------------------------------------------

_BROWSER_TASK_RE = re.compile(
    r"\b(go\s+to|navigate\s+to|visit|open\s+site)\b.{0,80}"
    r"\b(and|then)\b.{0,80}"
    r"\b(click|check|compare|search|buy|add|fill|select|price|prices|product|products|"
    r"login|signup|submit|form|extract|scrape|order|cart|book|download)\b"
    r"|"
    r"\b(browser\s*task|browser\s*workflow|web\s+automation|browser\s+automation|"
    r"do\s+the\s+same|do\s+it\s+again|repeat\s+that|run\s+again)\b",
    re.I | re.S,
)


def _looks_like_browser_task(user_input: str) -> bool:
    """
    Quick heuristic to detect browser automation tasks even when the
    Supervisor misses the intent (e.g. ambiguous phrasing).
    Used as a fallback in the browser pattern intercept.
    """
    return bool(_BROWSER_TASK_RE.search(user_input))


# ---------------------------------------------------------------------------
# Local tool execution (no ReAct loop)
# ---------------------------------------------------------------------------


def _execute_tool_directly(tool_name: str, args: dict, lc_tools: list, ask_llm_fn=None) -> tuple[str, int]:
    """
    Execute a tool directly without any ReAct reasoning loop.

    Returns:
        (result_string, tool_internal_llm_calls)
    """
    tool_internal_calls = 0

    # Find the tool
    tool_map = {t.name: t for t in lc_tools}
    tool = tool_map.get(tool_name)

    if not tool:
        return f"ERROR: Tool '{tool_name}' not found", 0

    # Inject ask_llm for web tools
    if tool_name in ("web_search", "browse_website", "browser_scrape") and ask_llm_fn:
        tool.ask_llm = ask_llm_fn
        tool_internal_calls = 1  # web tools use ask_llm internally

    try:
        result = tool._run(json.dumps(args))
        return result, tool_internal_calls
    except Exception as e:
        return f"Tool error ({tool_name}): {e}", 0


# ---------------------------------------------------------------------------
# Alternative tool fallback
# ---------------------------------------------------------------------------

_TOOL_ALTERNATIVES = {
    "browse_website": ["web_search"],
    "browser_scrape": ["web_search", "browse_website"],
    "web_search": ["browse_website"],
    "read_file": ["search_files"],
    "ping_host": ["check_port_open"],
}


def _get_alternative_tools(tool_name: str) -> list[str]:
    """Get alternative tools to try if the primary one fails."""
    return _TOOL_ALTERNATIVES.get(tool_name, [])


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def execute_local_first(
    user_input: str,
    supervisor,
    tool_registry,
    lc_tools: list,
    tiny_llm=None,
    cloud_provider=None,
    project_id: str = "",
    console=None,
) -> LocalFirstResult:
    """
    Execute a user request through the local-first pipeline.

    This is the main entry point. It routes through:
        1. Local Supervisor
        2. Chroma retrieval
        3. Deterministic or Tiny LLM tool selection
        4. Direct tool execution (no ReAct)
        5. Deterministic verification
        6. Cloud escalation only if needed

    Args:
        user_input: The user's request.
        supervisor: Supervisor instance for rule-based classification.
        tool_registry: ToolRegistry for Chroma semantic search.
        lc_tools: List of LangChain tool wrappers.
        tiny_llm: Optional TinyLLM instance.
        cloud_provider: Optional CloudLLMProvider for escalation.
        project_id: Current project ID.
        console: Optional Rich console for debug output.

    Returns:
        LocalFirstResult with full execution metrics.
    """
    t0 = time.time()
    result = LocalFirstResult()
    log = _RoutingLog(console)

    # ── Step 1: Local Supervisor ──────────────────────────────────────
    log.header(user_input)
    decision = supervisor.classify(user_input)
    result.execution_path.append("local_supervisor")
    result.intent = decision.intent
    result.complexity = decision.complexity
    result.supervisor_confidence = decision.confidence
    result.agent_used = decision.agent

    log.supervisor(decision)

    # ── Step 2: Chroma semantic retrieval ─────────────────────────────
    chroma_results = []
    if tool_registry:
        chroma_results = tool_registry.search_all_collections(user_input, n_results=5)
        result.execution_path.append("chroma")
        if chroma_results:
            result.chroma_confidence = 1.0 - chroma_results[0].get("distance", 1.0)
            log.chroma(chroma_results)
        else:
            log.info("Chroma: no matching tools found")

    # ── Step 3: Should we escalate to cloud? ──────────────────────────
    should_escalate, reason = should_escalate_to_cloud(decision, chroma_results)

    if should_escalate:
        # ── Browser Pattern Intercept (BEFORE cloud escalation) ──────
        # If intent is browser_automation, check ChromaDB for a saved pattern.
        # Pattern found   → replay with 0 cloud calls (return here)
        # No pattern found → escalate to cloud in recording mode
        # Unknown intent   → still check, because supervisor may have missed it
        _is_browser = (
            decision.intent == "browser_automation"
            or _looks_like_browser_task(user_input)
        )
        if _is_browser and project_id:
            try:
                from ecogent_experiment.browser_workflow.manager import BrowserWorkflowManager
                _chroma_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "chroma",
                )
                _projects_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "projects",
                )
                _bwm = BrowserWorkflowManager(
                    project_id=project_id,
                    chroma_dir=_chroma_dir,
                    projects_dir=_projects_dir,
                    cloud_provider=cloud_provider,
                )
                _pattern_meta = _bwm.pattern_store.find_pattern(user_input)

                if _pattern_meta:
                    # ── REPLAY — no cloud call needed ───────────────
                    _pattern = _bwm.pattern_store.get_pattern(_pattern_meta)
                    if _pattern:
                        log.info(
                            f"Browser pattern found: {_pattern_meta['pattern_id']} "
                            f"(distance: {_pattern_meta.get('distance', 0):.2f}) — replaying"
                        )
                        from ecogent_experiment.browser_workflow.replayer import BrowserReplayEngine
                        _replayer = BrowserReplayEngine(cloud_provider=cloud_provider)
                        _replay_res = _replayer.replay(
                            pattern=_pattern,
                            pattern_store=_bwm.pattern_store,
                            variables={},
                            console=console,
                        )
                        result.execution_path.append("browser_replay")
                        result.output = _replay_res.summary
                        result.cloud_llm_calls = _replay_res.cloud_recovery_count
                        result.local_tool_calls = len(_pattern.steps)
                        result.success = _replay_res.success
                        result.tool_used = "browser_task"
                        result.latency_ms = (time.time() - t0) * 1000
                        log.summary(result)
                        return result

                # No pattern — escalate in recording mode
                # Inject hint if pattern exists but was missed by supervisor
                _hint = _bwm.get_pattern_hint(user_input)
                result.cloud_escalation_context = {
                    "mode": "browser_recording",
                    "project_id": project_id,
                    "task": user_input,
                    "pattern_hint": _hint,
                }
            except Exception as _bwe:
                log.info(f"Browser pattern check failed: {_bwe}")

        result.cloud_escalated = True
        result.execution_path.append("cloud_escalation")
        log.escalate(reason)
        result.latency_ms = (time.time() - t0) * 1000
        return result

    # ── Step 4: Select tool ───────────────────────────────────────────
    selected_tool = decision.tool

    # If supervisor picked a tool AND Chroma confirms it, use it directly
    if selected_tool and chroma_results:
        chroma_tools = [c["tool_key"] for c in chroma_results[:3]]
        if selected_tool in chroma_tools:
            log.tool_match(selected_tool, "deterministic", decision.confidence)
        else:
            # Supervisor picked one tool, Chroma picked another — use Chroma's top if distance is very low
            if chroma_results[0].get("distance", 1.0) < 0.25:
                selected_tool = chroma_results[0]["tool_key"]
                log.tool_match(selected_tool, "chroma_override", result.chroma_confidence)

    # If supervisor didn't pick a tool, use Chroma's top result
    elif not selected_tool and chroma_results and chroma_results[0].get("distance", 1.0) < 0.5:
        selected_tool = chroma_results[0]["tool_key"]
        log.tool_match(selected_tool, "chroma", result.chroma_confidence)

    # If still no tool — try Tiny LLM
    if not selected_tool and tiny_llm:
        result.execution_path.append("tiny_llm")
        result.tiny_llm_calls += 1
        candidates = [
            {"tool_key": t.name, "description": t.description[:60]}
            for t in lc_tools[:10]
        ]
        names = [f"{c['tool_key']}: {c['description']}" for c in candidates]
        try:
            llm_dec = tiny_llm.select_tool(user_input, names)
            if llm_dec.json_valid and llm_dec.confidence >= 0.65 and llm_dec.tool:
                key = str(llm_dec.tool).lower().strip()
                for t in lc_tools:
                    if t.name.lower() == key or key in t.name.lower():
                        selected_tool = t.name
                        break
                if selected_tool:
                    log.tool_match(selected_tool, "tiny_llm", llm_dec.confidence)
        except Exception:
            pass
    elif not selected_tool:
        log.info("Tiny LLM: SKIPPED (not available)")

    # If STILL no tool — escalate
    if not selected_tool:
        result.cloud_escalated = True
        result.execution_path.append("cloud_escalation")
        log.escalate("no_tool_selected")
        result.latency_ms = (time.time() - t0) * 1000
        return result

    if tiny_llm and "tiny_llm" not in result.execution_path:
        log.skip("Tiny LLM", "deterministic match sufficient")
    log.skip("Cloud LLM", "local execution path")

    result.tool_used = selected_tool

    # ── Step 5: Extract arguments & execute ───────────────────────────
    args = _extract_tool_args(user_input, selected_tool, decision.intent)
    result.execution_path.append(f"tool:{selected_tool}")

    # Create ask_llm callback that counts internal calls
    ask_llm_fn = None
    if cloud_provider:
        def ask_llm_fn(prompt):
            result.tool_internal_llm_calls += 1
            return cloud_provider.generate_plan(prompt).get("answer", "")

    log.executing(selected_tool, args)

    tool_output, internal_calls = _execute_tool_directly(
        selected_tool, args, lc_tools, ask_llm_fn
    )
    result.local_tool_calls += 1
    result.tool_internal_llm_calls += internal_calls

    # ── Step 6: Handle failure with local fallback ────────────────────
    if tool_output.startswith("ERROR:") or tool_output.startswith("Tool error"):
        log.tool_failure(selected_tool, tool_output)

        alternatives = _get_alternative_tools(selected_tool)
        for alt_tool in alternatives:
            log.info(f"Local fallback: trying {alt_tool}")
            result.execution_path.append(f"fallback:{alt_tool}")

            alt_args = _extract_tool_args(user_input, alt_tool, decision.intent)
            alt_output, alt_internal = _execute_tool_directly(
                alt_tool, alt_args, lc_tools, ask_llm_fn
            )
            result.local_tool_calls += 1
            result.tool_internal_llm_calls += alt_internal

            if not alt_output.startswith("ERROR:") and not alt_output.startswith("Tool error"):
                tool_output = alt_output
                result.tool_used = alt_tool
                log.info(f"Fallback {alt_tool} succeeded")
                break
            else:
                log.tool_failure(alt_tool, alt_output)
        else:
            # All local alternatives failed — check escalation
            should_esc, esc_reason = should_escalate_to_cloud(
                decision, chroma_results, tool_execution_failed=True,
                alternative_tools_available=False,
            )
            if should_esc:
                result.cloud_escalated = True
                result.execution_path.append("cloud_escalation")
                log.escalate(esc_reason)
                result.latency_ms = (time.time() - t0) * 1000
                return result

    # ── Step 7: Verification ──────────────────────────────────────────
    result.execution_path.append("verification")

    # 7a. Deterministic verification first
    det_result = deterministic_verify(decision.intent, selected_tool, tool_output)
    result.verification_calls += 1

    if det_result["passed"] is True:
        result.success = True
        result.output = tool_output
        result.verification_source = "deterministic"
        log.verification("deterministic", True, det_result["method"])
    elif det_result["passed"] is False:
        # Deterministic says FAILED — try Tiny LLM
        if tiny_llm:
            result.tiny_llm_calls += 1
            result.verification_calls += 1
            try:
                v = tiny_llm.verify_completion(user_input, str(tool_output)[:500])
                verified = v.get("verified", False)
                if verified:
                    result.success = True
                    result.output = tool_output
                    result.verification_source = "tiny_llm"
                    log.verification("tiny_llm", True, "semantic check passed")
                else:
                    result.success = False
                    result.output = tool_output
                    result.verification_source = "tiny_llm"
                    log.verification("tiny_llm", False, "semantic check failed")
            except Exception:
                result.success = False
                result.output = tool_output
                result.verification_source = "deterministic"
                log.verification("deterministic", False, det_result["message"])
        else:
            result.success = False
            result.output = tool_output
            result.verification_source = "deterministic"
            log.verification("deterministic", False, det_result["message"])
    else:
        # Indeterminate — try Tiny LLM, then accept
        if tiny_llm:
            result.tiny_llm_calls += 1
            result.verification_calls += 1
            try:
                v = tiny_llm.verify_completion(user_input, str(tool_output)[:500])
                verified = v.get("verified", True)  # default to True if ambiguous
                result.success = verified
                result.output = tool_output
                result.verification_source = "tiny_llm"
                log.verification("tiny_llm", verified, "semantic verification")
            except Exception:
                result.success = True
                result.output = tool_output
                result.verification_source = "none"
                log.verification("none", True, "accepted without verification")
        else:
            # No Tiny LLM, accept the result
            result.success = True
            result.output = tool_output
            result.verification_source = "none"
            log.verification("none", True, "accepted without verification")

    # ── Done ──────────────────────────────────────────────────────────
    result.latency_ms = (time.time() - t0) * 1000
    log.summary(result)
    return result


# ---------------------------------------------------------------------------
# Routing log — pretty debug output for research
# ---------------------------------------------------------------------------

class _RoutingLog:
    """Structured routing log for the CLI."""

    def __init__(self, console=None):
        self.console = console

    def _print(self, msg: str):
        if self.console:
            self.console.print(msg)

    def header(self, user_input: str):
        self._print(f"\n[bold blue]{'─' * 60}[/bold blue]")
        self._print(f"[bold blue][ECOGENT ROUTER][/bold blue]")
        self._print(f"  Request: [white]\"{user_input}\"[/white]")

    def supervisor(self, decision):
        conf = decision.confidence
        color = "green" if conf >= 0.7 else "yellow" if conf >= 0.5 else "red"
        tool_str = decision.tool or "none"
        self._print(
            f"  [green]✓[/green] Local Supervisor: "
            f"intent=[cyan]{decision.intent}[/cyan], "
            f"tool=[cyan]{tool_str}[/cyan], "
            f"complexity=[cyan]{decision.complexity}[/cyan], "
            f"confidence=[{color}]{conf:.2f}[/{color}]"
        )

    def chroma(self, results: list):
        if results:
            top = results[0]
            dist = top.get("distance", 1.0)
            conf = 1.0 - dist
            color = "green" if conf >= 0.7 else "yellow" if conf >= 0.5 else "red"
            self._print(
                f"  [green]✓[/green] Chroma: "
                f"matched [cyan]{top['tool_key']}[/cyan] "
                f"(distance: {dist:.2f}, confidence: [{color}]{conf:.2f}[/{color}])"
            )
            if len(results) > 1:
                others = ", ".join(r["tool_key"] for r in results[1:3])
                self._print(f"    [dim]Other candidates: {others}[/dim]")

    def tool_match(self, tool: str, source: str, confidence: float):
        color = "green" if confidence >= 0.7 else "yellow"
        self._print(
            f"  [green]✓[/green] Tool selected: [bold cyan]{tool}[/bold cyan] "
            f"(via {source}, confidence: [{color}]{confidence:.2f}[/{color}])"
        )

    def skip(self, component: str, reason: str):
        self._print(f"  [dim]→ {component}: SKIPPED — {reason}[/dim]")

    def escalate(self, reason: str):
        self._print(f"  [bold yellow]↑ CLOUD ESCALATION: {reason}[/bold yellow]")

    def executing(self, tool: str, args: dict):
        # Show args but hide verbose ones
        display_args = {k: v for k, v in args.items() if k != "task"}
        args_str = json.dumps(display_args, ensure_ascii=False) if display_args else ""
        self._print(f"\n  [bold]Executing:[/bold] [cyan]{tool}[/cyan] {args_str}")

    def tool_failure(self, tool: str, error: str):
        self._print(f"  [red]✗[/red] {tool} failed: {error[:80]}")

    def verification(self, source: str, passed: bool, method: str):
        icon = "[green]✓[/green]" if passed else "[red]✗[/red]"
        self._print(f"  {icon} Verification ({source}): {method}")

    def info(self, msg: str):
        self._print(f"  [dim]{msg}[/dim]")

    def summary(self, result: LocalFirstResult):
        self._print(f"\n  [bold]Cloud LLM calls:[/bold] [{'green' if result.cloud_llm_calls == 0 else 'red'}]{result.cloud_llm_calls}[/{'green' if result.cloud_llm_calls == 0 else 'red'}] | "
                     f"[bold]Tiny LLM calls:[/bold] [cyan]{result.tiny_llm_calls}[/cyan] | "
                     f"[bold]Local tool calls:[/bold] [cyan]{result.local_tool_calls}[/cyan]")
        if result.tool_internal_llm_calls > 0:
            self._print(f"  [dim]Tool-internal LLM calls: {result.tool_internal_llm_calls} (data extraction, not routing)[/dim]")
        self._print(f"[bold blue]{'─' * 60}[/bold blue]")
