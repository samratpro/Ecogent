"""
Phase 6 Tests: Tiny LLM Fallback Integration.
"""

import pytest
from unittest.mock import MagicMock

from ecogent_experiment.supervisor import Supervisor, SupervisorDecision
from ecogent_experiment.router import Router, ExecutionResult


class TestSupervisorFallback:
    """Test Supervisor integration with Tiny LLM."""
    
    def test_supervisor_uses_fallback(self):
        # Mock TinyLLM
        mock_tiny_llm = MagicMock()
        mock_tiny_llm.classify_task.return_value = SupervisorDecision(
            intent="data_processing",
            tool="custom_data_tool",
            agent="coding_agent",
            execution="cloud",
            escalate=True,
            confidence=0.85
        )
        
        supervisor = Supervisor(tiny_llm=mock_tiny_llm, confidence_threshold=0.7)
        
        # A task that won't match any deterministic rule
        decision = supervisor.classify("Can you parse this complex XML into a relational database schema?")
        
        # Should fallback to Tiny LLM
        assert decision.source == "tiny_llm"
        assert decision.llm_required is True
        assert decision.intent == "data_processing"
        assert decision.tool == "custom_data_tool"
        assert decision.escalate is True
        
        # Ensure Tiny LLM was called
        mock_tiny_llm.classify_task.assert_called_once()
        stats = supervisor.get_stats()
        assert stats["tiny_llm_resolved"] == 1


class TestRouterVerification:
    """Test Router integration with Tiny LLM verification."""
    
    def test_router_verifies_with_tiny_llm(self):
        # Mock executor
        mock_executor = MagicMock(return_value="File renamed successfully")
        
        # Mock TinyLLM
        mock_tiny_llm = MagicMock()
        mock_tiny_llm.verify_completion.return_value = {
            "verified": True,
            "reason": "Output confirms the rename operation."
        }
        
        router = Router(tool_executor=mock_executor, tiny_llm=mock_tiny_llm)
        
        decision = SupervisorDecision(
            execution="local",
            tool="rename_file",
            agent="os_agent"
        )
        
        result = router.execute(decision, "rename a.txt to b.txt", {"src": "a.txt", "dst": "b.txt"})
        
        assert result.success is True
        assert result.verified is True
        assert result.verification_source == "tiny_llm"
        
        # Ensure verification was called
        mock_tiny_llm.verify_completion.assert_called_once_with(
            "rename a.txt to b.txt", "File renamed successfully"
        )
