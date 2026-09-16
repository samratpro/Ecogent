"""
Phase 2 Tests: Local Supervisor and Execution Router.
"""

import pytest
from ecogent_experiment.supervisor import Supervisor, SupervisorDecision, CLASSIFICATION_RULES


# ============================================================
# Supervisor Rules-Based Classification Tests
# ============================================================


class TestSupervisorRules:
    """Test deterministic rules-based classification."""

    def setup_method(self):
        """Create supervisor without Tiny LLM (pure rules mode)."""
        self.supervisor = Supervisor(tiny_llm=None, confidence_threshold=0.5)

    # --- Filesystem ---

    def test_rename_file(self):
        decision = self.supervisor.classify("Rename report.csv to final.csv")
        assert decision.intent == "file_operation"
        assert decision.tool == "rename_file"
        assert decision.agent == "os_agent"
        assert decision.llm_required is False

    def test_read_file(self):
        decision = self.supervisor.classify("Read the contents of readme.txt")
        assert decision.intent == "file_operation"
        assert decision.tool == "read_file"

    def test_write_file(self):
        decision = self.supervisor.classify("Create a file called output.txt")
        assert decision.intent == "file_operation"
        assert decision.tool == "write_file"

    def test_copy_file(self):
        decision = self.supervisor.classify("Copy the file backup.zip to archive")
        assert decision.intent == "file_operation"
        assert decision.tool == "copy_file"

    def test_delete_file(self):
        decision = self.supervisor.classify("Delete the file temp.log")
        assert decision.intent == "file_operation"
        assert decision.tool == "delete_file"

    def test_list_directory(self):
        decision = self.supervisor.classify("List all files in the current directory")
        assert decision.intent == "file_operation"
        assert decision.tool == "list_directory"
        assert decision.complexity == "simple"

    def test_create_directory(self):
        decision = self.supervisor.classify("Create a new folder called output")
        assert decision.intent == "file_operation"
        assert decision.tool == "create_directory"

    def test_search_files(self):
        decision = self.supervisor.classify("Search for files matching *.csv")
        assert decision.intent == "file_operation"
        assert decision.tool == "search_files"

    def test_file_exists(self):
        decision = self.supervisor.classify("Check if the file data.csv exists")
        assert decision.intent == "file_operation"
        assert decision.tool == "file_exists"

    # --- Data ---

    def test_read_csv(self):
        decision = self.supervisor.classify("Read the CSV data from customers.csv")
        assert decision.intent == "data_processing"
        assert decision.tool == "read_csv"

    def test_inspect_csv(self):
        decision = self.supervisor.classify("Inspect the columns of sales.csv")
        assert decision.intent == "data_processing"
        assert decision.tool == "inspect_csv"

    def test_statistics(self):
        decision = self.supervisor.classify("Calculate statistics for the sales data")
        assert decision.intent == "data_processing"
        assert decision.tool == "calculate_statistics"

    def test_filter_data(self):
        decision = self.supervisor.classify("Filter the dataframe to only include rows where age > 30")
        assert decision.intent == "data_processing"
        assert decision.tool == "filter_dataframe"

    # --- System ---

    def test_system_info(self):
        decision = self.supervisor.classify("Show system information")
        assert decision.intent == "system_info"
        assert decision.tool == "system_info"

    # --- Testing ---

    def test_run_tests(self):
        decision = self.supervisor.classify("Run the unit tests with pytest")
        assert decision.intent == "testing"
        assert decision.tool == "run_python_test"

    # --- Complex tasks (should escalate) ---

    def test_code_generation_escalates(self):
        decision = self.supervisor.classify("Write a Python function to sort a list")
        assert decision.intent == "code_generation"
        assert decision.escalate is True

    def test_browsing_escalates(self):
        decision = self.supervisor.classify("Open the website https://example.com and scrape the page")
        assert decision.intent == "browsing"
        assert decision.escalate is True

    # --- Unknown tasks ---

    def test_unknown_task(self):
        decision = self.supervisor.classify("What is the meaning of life?")
        assert decision.intent == "unknown"
        assert decision.confidence < 0.5

    # --- Execution routing ---

    def test_simple_task_routes_locally(self):
        decision = self.supervisor.classify("Rename report.csv to final.csv")
        assert decision.execution == "local"
        assert decision.llm_required is False

    def test_complex_task_routes_to_cloud(self):
        decision = self.supervisor.classify("Write a Python script to build a REST API")
        assert decision.execution == "cloud"


class TestSupervisorStats:
    """Test supervisor statistics tracking."""

    def test_stats_incremented(self):
        supervisor = Supervisor(tiny_llm=None, confidence_threshold=0.5)

        supervisor.classify("Rename file.txt to new.txt")
        supervisor.classify("List files in the directory")
        supervisor.classify("What is quantum computing?")

        stats = supervisor.get_stats()
        assert stats["total_tasks"] == 3
        assert stats["rules_resolved"] >= 2
        assert stats["cloud_escalated"] >= 1


# ============================================================
# Router Tests
# ============================================================


class TestRouter:
    """Test execution router."""

    def test_local_execution_success(self):
        from ecogent_experiment.router import Router

        def mock_executor(tool_name, **kwargs):
            return {"status": "ok", "tool": tool_name}

        router = Router(tool_executor=mock_executor)
        decision = SupervisorDecision(
            intent="file_operation",
            tool="rename_file",
            agent="os_agent",
            execution="local",
            escalate=False,
        )

        result = router.execute(decision, "Rename file.txt")
        assert result.success is True
        assert result.execution_path == "local"
        assert result.tool_used == "rename_file"

    def test_local_execution_no_executor(self):
        from ecogent_experiment.router import Router

        router = Router(tool_executor=None)
        decision = SupervisorDecision(
            intent="file_operation",
            tool="rename_file",
            execution="local",
        )

        result = router.execute(decision, "Rename file.txt")
        assert result.success is False
        assert "No tool executor" in result.error

    def test_cloud_escalation_no_provider(self):
        from ecogent_experiment.router import Router

        router = Router()
        decision = SupervisorDecision(
            intent="code_generation",
            execution="cloud",
            escalate=True,
        )

        result = router.execute(decision, "Write a Python script")
        assert result.success is False
        assert result.execution_path == "cloud"

    def test_router_stats(self):
        from ecogent_experiment.router import Router

        def mock_executor(tool_name, **kwargs):
            return "done"

        router = Router(tool_executor=mock_executor)
        decision = SupervisorDecision(
            tool="list_directory",
            execution="local",
            escalate=False,
        )

        router.execute(decision, "List files")
        router.execute(decision, "List files again")

        stats = router.get_stats()
        assert stats["total_routed"] == 2
        assert stats["local_executions"] == 2
        assert stats["successful"] == 2

    def test_execution_result_to_dict(self):
        from ecogent_experiment.router import ExecutionResult

        result = ExecutionResult(
            success=True,
            output="test output",
            execution_path="local",
            tool_used="rename_file",
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["tool_used"] == "rename_file"
