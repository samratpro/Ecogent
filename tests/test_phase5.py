"""
Phase 5 Tests: JSON Workflow Engine.
"""

import os
import json
import pytest
import tempfile
from typing import Any

from ecogent_experiment.workflow import WorkflowEngine, WorkflowNode, TargetCondition


class TestWorkflowEngine:
    """Test the JSON workflow engine operations."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = WorkflowEngine(workflows_dir=self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_workflow(self):
        nodes = [
            {
                "node_id": "step1",
                "task_title": "Read file",
                "execution_tier": "local",
                "tool": "read_file"
            },
            {
                "node_id": "step2",
                "task_title": "Process data",
                "dependencies": ["step1"],
                "execution_tier": "cloud"
            }
        ]
        
        workflow = self.engine.create_workflow("Test Project", nodes)
        
        assert workflow.project_name == "Test Project"
        assert len(workflow.project_tree) == 2
        assert workflow.global_status.total_nodes == 2
        assert workflow.global_status.completion == 0.0
        
        # Check that file was saved
        path = os.path.join(self.tmpdir, f"{workflow.project_id}.json")
        assert os.path.exists(path)

    def test_load_workflow(self):
        # Create directly via save_workflow to test load
        from ecogent_experiment.workflow import ProjectTree, GlobalStatus
        
        workflow = ProjectTree(
            project_id="load_test_123",
            project_name="Load Test",
            global_status=GlobalStatus(total_nodes=0),
            project_tree=[]
        )
        self.engine.save_workflow(workflow)
        
        loaded = self.engine.load_workflow("load_test_123")
        assert loaded is not None
        assert loaded.project_name == "Load Test"
        assert loaded.project_id == "load_test_123"

    def test_find_next_pending(self):
        nodes = [
            {"node_id": "n1", "task_title": "Task 1"},
            {"node_id": "n2", "task_title": "Task 2", "dependencies": ["n1"]},
            {"node_id": "n3", "task_title": "Task 3", "dependencies": ["n1", "n2"]}
        ]
        workflow = self.engine.create_workflow("Dep Test", nodes)
        
        # Initially, only n1 has no dependencies met requirement
        next_node = self.engine.find_next_pending(workflow)
        assert next_node is not None
        assert next_node.node_id == "n1"
        
        # Complete n1
        self.engine.update_node(workflow, "n1", "completed")
        
        # Now n2 should be next
        next_node = self.engine.find_next_pending(workflow)
        assert next_node is not None
        assert next_node.node_id == "n2"

    def test_update_node(self):
        workflow = self.engine.create_workflow("Update Test", [{"node_id": "n1", "task_title": "Task 1"}])
        
        # Test in_progress
        self.engine.update_node(workflow, "n1", "in_progress")
        assert workflow.project_tree[0].status == "in_progress"
        assert workflow.project_tree[0].completion == 50.0
        assert workflow.global_status.current_node == "n1"
        
        # Test completed
        self.engine.update_node(workflow, "n1", "completed", result={"output": "success"})
        assert workflow.project_tree[0].status == "completed"
        assert workflow.project_tree[0].completion == 100.0
        assert workflow.project_tree[0].result == {"output": "success"}
        assert workflow.global_status.completed_nodes == 1
        assert workflow.global_status.completion == 100.0

    def test_execute_workflow(self):
        nodes = [
            {"node_id": "n1", "task_title": "Task 1"},
            {"node_id": "n2", "task_title": "Task 2", "dependencies": ["n1"]}
        ]
        workflow = self.engine.create_workflow("Exec Test", nodes)
        
        executed_nodes = []
        
        def mock_executor(node: WorkflowNode) -> Any:
            executed_nodes.append(node.node_id)
            return f"Result of {node.node_id}"
            
        result = self.engine.execute_workflow(workflow, mock_executor)
        
        assert result["executed"] == 2
        assert result["succeeded"] == 2
        assert result["completion"] == 100.0
        assert executed_nodes == ["n1", "n2"]
        
        # Verify persistence
        loaded = self.engine.load_workflow(workflow.project_id)
        assert loaded.project_tree[0].status == "completed"
        assert loaded.project_tree[1].status == "completed"
