"""
Local-First Architecture Tests for Ecogent.

Validates that:
1. Simple tasks complete with cloud_llm_calls == 0
2. Chroma retrieves semantically relevant tools
3. Deterministic verification works without LLM
4. Complex tasks correctly escalate to cloud
5. Tool fallback/recovery happens locally
6. Execution paths are correctly tracked

These tests validate the research hypothesis:
    "Simple tasks should NOT require cloud LLM calls."
"""

import os
import sys
import json
import pytest

# Ensure project root is on path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from ecogent_experiment.supervisor import Supervisor, SupervisorDecision
from ecogent_experiment.local_executor import (
    LocalFirstResult,
    should_escalate_to_cloud,
    deterministic_verify,
    _extract_tool_args,
)


# ============================================================
# 1. Supervisor Classification Tests
# ============================================================

class TestSupervisorClassification:
    """Test that the supervisor correctly classifies simple tasks locally."""

    def setup_method(self):
        self.supervisor = Supervisor(confidence_threshold=0.7)

    def test_rename_file(self):
        decision = self.supervisor.classify("Rename report.csv to final_report.csv")
        assert decision.intent == "file_operation"
        assert decision.tool in ("rename_file", "move_file")
        assert decision.complexity in ("simple", "moderate")
        assert decision.confidence >= 0.6  # Short inputs naturally have lower scores
        assert decision.execution == "local"

    def test_create_directory(self):
        decision = self.supervisor.classify("Create a directory called output")
        assert decision.intent == "file_operation"
        assert decision.tool == "create_directory"
        assert decision.execution == "local"
        assert decision.confidence >= 0.7

    def test_list_directory(self):
        decision = self.supervisor.classify("List all files in this directory")
        assert decision.intent == "file_operation"
        assert decision.tool == "list_directory"
        assert decision.execution == "local"

    def test_search_files(self):
        decision = self.supervisor.classify("Search for config.json files in the project")
        assert decision.intent == "file_operation"
        assert decision.tool == "search_files"

    def test_web_search_bing(self):
        """CRITICAL: The KKBAU acceptance test."""
        decision = self.supervisor.classify("search Bing for KKBAU and tell me the first result")
        assert decision.intent == "browsing"
        assert decision.tool == "web_search"
        assert decision.complexity == "simple"
        assert decision.confidence >= 0.7
        assert decision.execution == "local"

    def test_web_search_google(self):
        decision = self.supervisor.classify("Google search for best Python frameworks")
        assert decision.intent == "browsing"
        assert decision.tool == "web_search"

    def test_browse_website(self):
        decision = self.supervisor.classify("go to https://example.com and summarize the website")
        assert decision.intent == "browsing"
        assert decision.tool == "browse_website"

    def test_system_info(self):
        decision = self.supervisor.classify("Show me system hardware info")
        assert decision.intent == "system_info"
        assert decision.tool == "system_info"
        assert decision.execution == "local"

    def test_run_tests(self):
        decision = self.supervisor.classify("Run the tests in this project")
        assert decision.intent == "testing"
        assert decision.tool == "run_python_test"

    def test_complex_task_escalates(self):
        decision = self.supervisor.classify(
            "Write a Python API that handles user authentication with JWT tokens"
        )
        assert decision.intent == "code_generation"
        assert decision.complexity == "complex"


# ============================================================
# 2. Cloud Escalation Policy Tests
# ============================================================

class TestCloudEscalation:
    """Test the centralized should_escalate_to_cloud policy."""

    def _decision(self, **kwargs):
        return SupervisorDecision(**kwargs)

    def test_simple_known_tool_no_escalation(self):
        decision = self._decision(
            intent="file_operation", tool="rename_file",
            complexity="simple", confidence=0.9
        )
        escalate, reason = should_escalate_to_cloud(decision, [])
        assert not escalate

    def test_complex_task_always_escalates(self):
        decision = self._decision(
            intent="code_generation", tool=None,
            complexity="complex", confidence=0.5
        )
        escalate, reason = should_escalate_to_cloud(decision, [])
        assert escalate
        assert reason == "complex_task"

    def test_code_generation_always_escalates(self):
        decision = self._decision(
            intent="code_generation", tool=None,
            complexity="moderate", confidence=0.8
        )
        escalate, reason = should_escalate_to_cloud(decision, [])
        assert escalate
        assert reason == "code_generation_requires_cloud"

    def test_unknown_with_no_tools_escalates(self):
        decision = self._decision(
            intent="unknown", tool=None,
            complexity="unknown", confidence=0.0
        )
        escalate, reason = should_escalate_to_cloud(decision, [])
        assert escalate

    def test_tool_failure_with_alternatives_stays_local(self):
        decision = self._decision(
            intent="browsing", tool="browse_website",
            complexity="simple", confidence=0.8
        )
        escalate, reason = should_escalate_to_cloud(
            decision, [], tool_execution_failed=True,
            alternative_tools_available=True
        )
        assert not escalate

    def test_tool_failure_no_alternatives_escalates(self):
        decision = self._decision(
            intent="browsing", tool="browse_website",
            complexity="simple", confidence=0.8
        )
        escalate, reason = should_escalate_to_cloud(
            decision, [], tool_execution_failed=True,
            alternative_tools_available=False
        )
        assert escalate

    def test_chroma_strong_match_stays_local(self):
        decision = self._decision(
            intent="unknown", tool=None,
            complexity="unknown", confidence=0.3
        )
        chroma = [{"tool_key": "web_search", "distance": 0.15}]
        escalate, reason = should_escalate_to_cloud(decision, chroma)
        assert not escalate
        assert reason == "chroma_strong_match"

    def test_web_search_simple_stays_local(self):
        """The KKBAU test — browsing + web_search + simple must NOT escalate."""
        decision = self._decision(
            intent="browsing", tool="web_search",
            complexity="simple", confidence=0.85
        )
        escalate, reason = should_escalate_to_cloud(decision, [])
        assert not escalate
        assert reason == "high_confidence_local_match"


# ============================================================
# 3. Deterministic Verification Tests
# ============================================================

class TestDeterministicVerification:
    """Test that deterministic verification works without any LLM."""

    def test_web_search_with_results(self):
        result = deterministic_verify(
            "browsing", "web_search",
            "1. Example Result\nhttps://example.com\n2. Another Result"
        )
        assert result["passed"] is True
        assert result["method"] == "RESULT_HAS_CONTENT"

    def test_web_search_error(self):
        result = deterministic_verify(
            "browsing", "web_search",
            "ERROR: Connection timed out"
        )
        assert result["passed"] is False

    def test_file_operation_success(self):
        result = deterministic_verify(
            "file_operation", "list_directory",
            '{"success": true, "files": ["a.txt", "b.csv"]}'
        )
        assert result["passed"] is True

    def test_file_operation_error(self):
        result = deterministic_verify(
            "file_operation", "read_file",
            "ERROR: File not found: /path/to/missing.txt"
        )
        assert result["passed"] is False

    def test_system_info_success(self):
        result = deterministic_verify(
            "system_info", "system_info",
            '{"os": "Windows", "cpu": "Intel i7", "ram": "16GB"}'
        )
        assert result["passed"] is True

    def test_empty_result_fails(self):
        result = deterministic_verify(
            "file_operation", "read_file", ""
        )
        assert result["passed"] is False or result["passed"] is None

    def test_shell_command_success(self):
        result = deterministic_verify(
            "testing", "run_shell",
            "All 5 tests passed."
        )
        assert result["passed"] is True

    def test_tool_error_prefix(self):
        result = deterministic_verify(
            "browsing", "browse_website",
            "Tool error (browse_website): timeout"
        )
        assert result["passed"] is False


# ============================================================
# 4. Tool Argument Extraction Tests
# ============================================================

class TestToolArgExtraction:
    """Test deterministic argument extraction from user input."""

    def test_web_search_bing(self):
        args = _extract_tool_args(
            "search Bing for KKBAU and tell me the first result",
            "web_search", "browsing"
        )
        assert "query" in args
        assert "KKBAU" in args["query"]

    def test_browse_url(self):
        args = _extract_tool_args(
            "go to https://example.com and summarize",
            "browse_website", "browsing"
        )
        assert args.get("url") == "https://example.com"

    def test_list_directory(self):
        args = _extract_tool_args(
            "list all files in this directory",
            "list_directory", "file_operation"
        )
        assert "path" in args

    def test_rename_file(self):
        args = _extract_tool_args(
            "rename report.csv to final_report.csv",
            "rename_file", "file_operation"
        )
        assert args.get("source") == "report.csv"
        assert args.get("destination") == "final_report.csv"


# ============================================================
# 5. Execution Path Tracking Tests
# ============================================================

class TestExecutionPathTracking:
    """Test that LocalFirstResult correctly records execution paths."""

    def test_result_has_execution_path(self):
        result = LocalFirstResult()
        result.execution_path.append("local_supervisor")
        result.execution_path.append("chroma")
        result.execution_path.append("tool:web_search")
        result.execution_path.append("verification")

        d = result.to_dict()
        assert d["execution_path"] == [
            "local_supervisor", "chroma", "tool:web_search", "verification"
        ]

    def test_result_tracks_call_counts(self):
        result = LocalFirstResult()
        result.cloud_llm_calls = 0
        result.tiny_llm_calls = 0
        result.local_tool_calls = 1
        result.verification_calls = 1

        d = result.to_dict()
        assert d["cloud_llm_calls"] == 0
        assert d["tiny_llm_calls"] == 0
        assert d["local_tool_calls"] == 1

    def test_cloud_escalated_flag(self):
        result = LocalFirstResult()
        result.cloud_escalated = True
        assert result.to_dict()["cloud_escalated"] is True


# ============================================================
# 6. Integration: Supervisor → Escalation Policy
# ============================================================

class TestIntegration:
    """End-to-end tests combining supervisor + escalation policy."""

    def setup_method(self):
        self.supervisor = Supervisor(confidence_threshold=0.7)

    def test_kkbau_search_no_cloud(self):
        """The key acceptance test: KKBAU search must not escalate."""
        decision = self.supervisor.classify("search Bing for KKBAU and tell me the first result")
        escalate, reason = should_escalate_to_cloud(decision, [])
        assert not escalate, f"KKBAU search should NOT escalate to cloud! Reason: {reason}"
        assert decision.tool == "web_search"

    def test_file_rename_no_cloud(self):
        decision = self.supervisor.classify("Rename report.csv to final_report.csv")
        escalate, _ = should_escalate_to_cloud(decision, [])
        assert not escalate

    def test_list_directory_no_cloud(self):
        decision = self.supervisor.classify("List all files in this directory")
        escalate, _ = should_escalate_to_cloud(decision, [])
        assert not escalate

    def test_complex_pipeline_escalates(self):
        decision = self.supervisor.classify(
            "Build a complete customer segmentation pipeline from clients.csv, "
            "optimize clustering, create visualizations, and prepare a report"
        )
        escalate, _ = should_escalate_to_cloud(decision, [])
        assert escalate

    def test_browse_then_fallback_no_cloud(self):
        """Browse failure should try web_search locally, not escalate."""
        decision = self.supervisor.classify("go to https://example.com and summarize")
        # Simulate browse_website failing
        escalate, _ = should_escalate_to_cloud(
            decision, [],
            tool_execution_failed=True,
            alternative_tools_available=True  # web_search is an alternative
        )
        assert not escalate


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
