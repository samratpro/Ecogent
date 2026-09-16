"""
Phase 4 Tests: Chroma Semantic Tool Registry.
"""

import os
import pytest
import tempfile

try:
    import chromadb
except ImportError:
    chromadb = None


@pytest.mark.skipif(chromadb is None, reason="chromadb not installed")
class TestToolRegistry:
    """Test the semantic tool registry backed by Chroma."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from ecogent_experiment.tool_registry import ToolRegistry
        self.registry = ToolRegistry(chroma_dir=self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_collections_created(self):
        stats = self.registry.get_stats()
        assert "builtin_tools" in stats
        assert "generated_tools" in stats
        assert "project_tools" in stats

    def test_register_and_get_tool(self):
        success = self.registry.register_tool(
            tool_key="test_tool",
            natural_name="Test Tool",
            description="A tool for testing purposes",
            category="testing",
            agent="testing_agent",
            persistent=True,
            collection="builtin_tools"
        )
        assert success is True

        tool = self.registry.get_tool("test_tool", "builtin_tools")
        assert tool is not None
        assert tool["tool_key"] == "test_tool"
        assert tool["natural_name"] == "Test Tool"
        assert tool["category"] == "testing"

    def test_query_tools(self):
        self.registry.register_tool(
            tool_key="rename_file",
            natural_name="Rename File",
            description="Rename a local file from one path to another",
            category="filesystem",
            agent="os_agent",
        )
        
        # Test semantic search - doesn't need to match exactly
        results = self.registry.query_tools("change the name of a document")
        assert len(results) > 0
        assert results[0]["tool_key"] == "rename_file"

    def test_deregister_tool(self):
        # Register a generated tool
        self.registry.register_tool(
            tool_key="custom_tool",
            natural_name="Custom Tool",
            description="Custom generated tool",
            category="data",
            agent="coding_agent",
            persistent=False,
            collection="generated_tools"
        )
        
        assert self.registry.get_tool("custom_tool", "generated_tools") is not None
        
        success = self.registry.deregister_tool("custom_tool", "generated_tools")
        assert success is True
        assert self.registry.get_tool("custom_tool", "generated_tools") is None

    def test_cannot_deregister_persistent_tool(self):
        self.registry.register_tool(
            tool_key="builtin_test",
            natural_name="Builtin Test",
            description="Persistent tool",
            category="system",
            agent="os_agent",
            persistent=True,
            collection="builtin_tools"
        )
        
        success = self.registry.deregister_tool("builtin_test", "builtin_tools")
        assert success is False
        assert self.registry.get_tool("builtin_test", "builtin_tools") is not None

    def test_list_tools(self):
        self.registry.register_tool("tool1", "Tool 1", "desc 1", "cat1", "agent1")
        self.registry.register_tool("tool2", "Tool 2", "desc 2", "cat2", "agent2")
        
        tools = self.registry.list_tools("builtin_tools")
        assert len(tools) == 2
        keys = [t["tool_key"] for t in tools]
        assert "tool1" in keys
        assert "tool2" in keys
