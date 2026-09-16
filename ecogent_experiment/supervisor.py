"""
Local NLP Supervisor.

Deterministic rule-based supervisor that handles obvious tasks without any LLM.
For uncertain tasks, it delegates to the Tiny LLM fallback.

This is the first layer in the Ecogent architecture:
  User Input -> Supervisor -> (Local Tool | Tiny LLM | Cloud)
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# Intent-to-Tool Mapping Rules
# ============================================================

# Pattern-based intent classification rules
# Each rule: (compiled_regex_pattern, intent, tool, agent, complexity)
CLASSIFICATION_RULES = [
    # Filesystem operations
    (re.compile(r"\b(rename|change\s*(?:the\s*)?name)\b", re.I), "file_operation", "rename_file", "os_agent", "simple"),
    (re.compile(r"\b(read|open|show|display|cat|view|print)\b.*\b(file|content|text|readme)\b", re.I), "file_operation", "read_file", "os_agent", "simple"),
    (re.compile(r"\b(write|create|save|make)\b.*\bfile\b", re.I), "file_operation", "write_file", "os_agent", "simple"),
    (re.compile(r"\b(copy|duplicate|clone)\b.*\bfile\b", re.I), "file_operation", "copy_file", "os_agent", "simple"),
    (re.compile(r"\b(move|relocate|transfer)\b.*\bfile\b", re.I), "file_operation", "move_file", "os_agent", "simple"),
    (re.compile(r"\b(delete|remove|erase|rm)\b.*\bfile\b", re.I), "file_operation", "delete_file", "os_agent", "simple"),
    (re.compile(r"\b(list|ls|dir|show)\b.*\b(files?|directory|director|folder|content)", re.I), "file_operation", "list_directory", "os_agent", "simple"),
    (re.compile(r"\b(create|make|mkdir)\b.*\b(directory|director|folder)\b", re.I), "file_operation", "create_directory", "os_agent", "simple"),
    (re.compile(r"\b(search|find|locate|grep)\b.*\b(files?|pattern|csv|txt|json)\b", re.I), "file_operation", "search_files", "os_agent", "simple"),
    (re.compile(r"\b(exist|check|is there)\b.*\b(files?|directory|director|folder)\b", re.I), "file_operation", "file_exists", "os_agent", "simple"),

    # Data operations
    (re.compile(r"\bread\b.*\bcsv\b", re.I), "data_processing", "read_csv", "os_agent", "simple"),
    (re.compile(r"\b(inspect|describe|schema|columns?|structure)\b.*\bcsv\b", re.I), "data_processing", "inspect_csv", "os_agent", "simple"),
    (re.compile(r"\b(statistics?|stats?|mean|median|average|std|summary)\b", re.I), "data_processing", "calculate_statistics", "os_agent", "moderate"),
    (re.compile(r"\b(filter|where|select|subset)\b.*\b(data|rows?|records?|dataframe)\b", re.I), "data_processing", "filter_dataframe", "os_agent", "moderate"),
    (re.compile(r"\b(save|write|export)\b.*\bcsv\b", re.I), "data_processing", "save_csv", "os_agent", "simple"),
    (re.compile(r"\b(train|model|predict|automl|flaml|machine learning|regression|classification)\b", re.I), "data_processing", "run_flaml_automl", "os_agent", "moderate"),

    # System operations
    (re.compile(r"\b(system|hardware|cpu|ram|memory|disk|os)\b.*\b(info|information|details?|status)\b", re.I), "system_info", "system_info", "os_agent", "simple"),
    (re.compile(r"\b(process|running|pid|task)\b.*\b(info|list|status)\b", re.I), "system_info", "process_info", "os_agent", "simple"),

    # Testing
    (re.compile(r"\b(run|execute)\b.*\b(tests?|pytest|unittest)\b", re.I), "testing", "run_python_test", "testing_agent", "moderate"),
    (re.compile(r"\b(verify|validate|check)\b.*\bfile\b", re.I), "testing", "verify_file", "testing_agent", "simple"),
    (re.compile(r"\b(verify|validate|check)\b.*\b(director|folder)\b", re.I), "testing", "verify_directory", "testing_agent", "simple"),

    # Web search (dedicated — most common simple web task)
    (re.compile(r"\b(search|find|look\s*up|query)\b.*\b(bing|google|duckduckgo|yahoo|web|online|internet)\b", re.I), "browsing", "web_search", "browser_agent", "simple"),
    (re.compile(r"\b(bing|google|duckduckgo)\b.*\b(search|find|result)\b", re.I), "browsing", "web_search", "browser_agent", "simple"),
    # Generic "search for X" — but only if no file/pattern keywords present (handled above)
    (re.compile(r"\b(search|find|look\s*up)\b.*\bfor\b(?!.*\b(file|pattern|csv|txt|json|directory)\b)", re.I), "browsing", "web_search", "browser_agent", "simple"),

    # Browsing / scraping (visit a specific URL)
    (re.compile(r"\b(browse|open|visit|navigate|go\s+to)\b.*\b(https?://|url|site|page|website)\b", re.I), "browsing", "browse_website", "browser_agent", "simple"),
    (re.compile(r"\bhttps?://\S+", re.I), "browsing", "browse_website", "browser_agent", "simple"),
    (re.compile(r"\b(scrape|crawl)\b.*\b(web|url|site|page|http)\b", re.I), "browsing", "browser_scrape", "browser_agent", "moderate"),
    (re.compile(r"\b(summar|extract|read)\b.*\b(website|webpage|page|site|url|https?)\b", re.I), "browsing", "browse_website", "browser_agent", "simple"),

    # ── Browser Automation (multi-step interactive) ───────────────────────────
    # Navigate + interact pattern: "go to X ... and then click/check/compare/..."
    (re.compile(
        r"\b(go\s+to|navigate\s+to|open\s+site|visit)\b.{0,80}"
        r"\b(and|then)\b.{0,80}"
        r"\b(click|check|compare|search|buy|add|fill|select|price|prices|product|products|"
        r"login|signup|submit|form|list|extract|scrape|order|cart|book|register|download)\b",
        re.I | re.S
    ), "browser_automation", "browser_task", "browser_agent", "complex"),

    # Explicit browser task commands
    (re.compile(
        r"\b(automate|browser\s*task|browser\s*workflow|interact\s+with\s+(the\s+)?site|"
        r"fill\s+out\s+(a\s+)?form|web\s+automation|browser\s+automation)\b",
        re.I
    ), "browser_automation", "browser_task", "browser_agent", "complex"),

    # Repeated task detection — "do the same", "do it again", "repeat that"
    (re.compile(
        r"\b(do\s+the\s+same|same\s+task|repeat\s+(that|this|it)|do\s+it\s+again|"
        r"run\s+(it\s+)?again|same\s+as\s+before|like\s+before)\b",
        re.I
    ), "browser_automation", "browser_task", "browser_agent", "complex"),

    # Code generation (always escalates)
    (re.compile(r"\b(write|create|generate|build|implement|code|program|script)\b.*\b(python|java|code|function|class|script|program|api|app)\b", re.I), "code_generation", None, "coding_agent", "complex"),
]


@dataclass
class SupervisorDecision:
    """Structured decision from the supervisor."""
    intent: str = "unknown"
    complexity: str = "unknown"
    tool: Optional[str] = None
    agent: Optional[str] = None
    execution: str = "cloud"
    escalate: bool = True
    confidence: float = 0.0
    source: str = "unknown"  # "rules", "tiny_llm", "fallback"
    llm_required: bool = True

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "complexity": self.complexity,
            "tool": self.tool,
            "agent": self.agent,
            "execution": self.execution,
            "escalate": self.escalate,
            "confidence": self.confidence,
            "source": self.source,
            "llm_required": self.llm_required,
        }


@dataclass
class SupervisorStats:
    """Accumulated supervisor statistics."""
    total_tasks: int = 0
    rules_resolved: int = 0
    tiny_llm_resolved: int = 0
    cloud_escalated: int = 0

    def to_dict(self) -> dict:
        return {
            "total_tasks": self.total_tasks,
            "rules_resolved": self.rules_resolved,
            "tiny_llm_resolved": self.tiny_llm_resolved,
            "cloud_escalated": self.cloud_escalated,
        }


class Supervisor:
    """
    Deterministic local supervisor.

    First inspects the user's request using keyword/pattern matching.
    For obvious tasks, routes directly to tools without any LLM call.
    For uncertain tasks, delegates to the Tiny LLM fallback.

    This is the core of the cost-reduction architecture.
    """

    def __init__(self, tiny_llm=None, confidence_threshold: float = 0.7):
        """
        Initialize the supervisor.

        Args:
            tiny_llm: Optional TinyLLM instance for fallback decisions.
            confidence_threshold: Minimum confidence for rules-based decisions.
        """
        self.tiny_llm = tiny_llm
        self.confidence_threshold = confidence_threshold if confidence_threshold != 0.7 else 0.60
        self.stats = SupervisorStats()

    def classify(self, task: str) -> SupervisorDecision:
        """
        Classify a user task and decide execution path.

        Decision flow:
        1. Try rules-based classification
        2. If confident -> return local decision (no LLM needed)
        3. If uncertain and Tiny LLM available -> consult Tiny LLM
        4. If still uncertain -> escalate to cloud

        Args:
            task: The user's request text.

        Returns:
            SupervisorDecision with routing information.
        """
        self.stats.total_tasks += 1

        # Step 1: Rules-based classification
        decision = self._classify_by_rules(task)

        if decision.confidence >= self.confidence_threshold:
            # High confidence from rules alone
            decision.source = "rules"
            decision.llm_required = False
            self.stats.rules_resolved += 1
            return decision

        # Step 2: Tiny LLM fallback (if available)
        if self.tiny_llm is not None:
            llm_decision = self._classify_by_tiny_llm(task, decision)
            if llm_decision.confidence >= self.confidence_threshold:
                llm_decision.source = "tiny_llm"
                llm_decision.llm_required = True
                self.stats.tiny_llm_resolved += 1
                return llm_decision

        # Step 3: Cloud escalation
        decision.execution = "cloud"
        decision.escalate = True
        decision.source = "fallback"
        self.stats.cloud_escalated += 1
        return decision

    def _classify_by_rules(self, task: str) -> SupervisorDecision:
        """
        Classify using deterministic pattern matching.

        Returns a decision with confidence reflecting match quality.
        """
        best_match = None
        best_score = 0.0

        for pattern, intent, tool, agent, complexity in CLASSIFICATION_RULES:
            match = pattern.search(task)
            if match:
                # Score based on match length relative to input length
                match_len = match.end() - match.start()
                score = min(1.0, match_len / max(len(task), 1) + 0.5)

                if score > best_score:
                    best_score = score
                    best_match = (intent, tool, agent, complexity)

        if best_match:
            intent, tool, agent, complexity = best_match
            is_simple = complexity in ("simple", "moderate")

            return SupervisorDecision(
                intent=intent,
                complexity=complexity,
                tool=tool,
                agent=agent,
                execution="local" if is_simple and tool else "cloud",
                escalate=not is_simple or tool is None,
                confidence=best_score,
                source="rules",
                llm_required=False,
            )

        # No rules matched
        return SupervisorDecision(
            intent="unknown",
            complexity="unknown",
            confidence=0.0,
            source="rules",
        )

    def _classify_by_tiny_llm(
        self, task: str, rules_decision: SupervisorDecision
    ) -> SupervisorDecision:
        """
        Consult the Tiny LLM for uncertain classifications.

        Merges LLM decision with any partial rules-based signals.
        """
        llm_decision = self.tiny_llm.classify_task(task)

        # Merge: prefer rules-based tool if rules found one
        tool = rules_decision.tool or llm_decision.tool
        agent = rules_decision.agent

        # Map LLM intent to agent if rules didn't pick one
        if not agent and llm_decision.intent:
            agent = _intent_to_agent(llm_decision.intent)

        return SupervisorDecision(
            intent=llm_decision.intent or rules_decision.intent,
            complexity=llm_decision.complexity,
            tool=tool,
            agent=agent,
            execution=llm_decision.execution,
            escalate=llm_decision.escalate,
            confidence=llm_decision.confidence,
            source="tiny_llm",
            llm_required=True,
        )

    def get_stats(self) -> dict:
        """Get accumulated supervisor statistics."""
        return self.stats.to_dict()


def _intent_to_agent(intent: str) -> Optional[str]:
    """Map an intent to the appropriate agent."""
    mapping = {
        "file_operation": "os_agent",
        "data_processing": "os_agent",
        "system_info": "os_agent",
        "code_generation": "coding_agent",
        "testing": "testing_agent",
        "browsing": "browser_agent",
    }
    return mapping.get(intent)
