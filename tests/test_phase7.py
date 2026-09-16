"""
Phase 7 Tests: Mock Cloud Escalation + Agents.
"""

import pytest
from ecogent_experiment.providers.mock_cloud import MockCloudProvider
from ecogent_experiment.providers.langgraph_adapter import LangGraphAdapter
from ecogent_experiment.agents.coding_agent import CodingAgent
from ecogent_experiment.tool_generator import ToolGenerator

class TestMockProviders:
    def test_mock_cloud_provider(self):
        provider = MockCloudProvider(simulate_latency_ms=0)
        result = provider.generate_plan("Write some python code")
        
        assert result["input_tokens"] > 0
        assert result["output_tokens"] > 0
        assert "python" in result["answer"].lower()

    def test_langgraph_adapter(self):
        adapter = LangGraphAdapter()
        result = adapter.generate_plan("Test task")
        assert "LangGraph execution" in result["answer"]


class TestAgents:
    def test_coding_agent_cloud_escalation(self):
        provider = MockCloudProvider(simulate_latency_ms=0)
        agent = CodingAgent(cloud_provider=provider)
        
        result = agent.execute("Write a complex python app")
        assert "[CodingAgent Cloud]" in result
        
    def test_coding_agent_local(self):
        agent = CodingAgent(cloud_provider=None)
        result = agent.execute("Write a simple loop")
        assert "[CodingAgent Local]" in result


class TestToolGenerator:
    def test_tool_generation(self):
        class DummyRegistry:
            def register_tool(self, **kwargs):
                pass
                
        provider = MockCloudProvider(simulate_latency_ms=0)
        registry = DummyRegistry()
        generator = ToolGenerator(provider, registry)
        
        tool = generator.generate_tool("Reverse a string")
        assert tool is not None
        assert "tool_key" in tool
        assert "code" in tool
