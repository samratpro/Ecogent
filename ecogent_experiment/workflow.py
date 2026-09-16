"""
JSON Workflow / Project Tree Engine.

Machine-readable workflow state for complex multi-step tasks.
Each workflow is a DAG of nodes with dependencies, assertions,
and execution tracking.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# Data Models
# ============================================================


class TargetCondition(BaseModel):
    """A verification condition for a workflow node."""
    assertion_type: str  # FILE_EXISTS, CSV_COLUMN_EXISTS, etc.
    target: Any  # Path string or dict with params


class WorkflowNode(BaseModel):
    """A single node in the project workflow tree."""
    node_id: str
    task_title: str
    execution_tier: str = "local"  # local, cloud
    status: str = "pending"  # pending, in_progress, completed, failed, skipped
    completion: float = 0.0  # 0-100
    dependencies: list[str] = Field(default_factory=list)
    target_conditions: list[TargetCondition] = Field(default_factory=list)
    result: Optional[Any] = None
    error: Optional[str] = None
    agent: Optional[str] = None
    tool: Optional[str] = None
    timestamps: dict = Field(default_factory=dict)


class GlobalStatus(BaseModel):
    """Global workflow status."""
    completion: float = 0.0
    current_node: Optional[str] = None
    total_nodes: int = 0
    completed_nodes: int = 0
    failed_nodes: int = 0


class ProjectTree(BaseModel):
    """Complete project workflow."""
    project_id: str
    project_name: str
    global_status: GlobalStatus = Field(default_factory=GlobalStatus)
    project_tree: list[WorkflowNode] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


# ============================================================
# Workflow Engine
# ============================================================


class WorkflowEngine:
    """
    Manages JSON workflow/project trees.

    Handles creation, loading, saving, execution tracking,
    and node dependency resolution.
    """

    def __init__(self, workflows_dir: str):
        """
        Initialize the workflow engine.

        Args:
            workflows_dir: Directory to store workflow JSON files.
        """
        self.workflows_dir = os.path.abspath(workflows_dir)
        os.makedirs(self.workflows_dir, exist_ok=True)

    def create_workflow(
        self,
        project_name: str,
        nodes: list[dict],
        project_id: Optional[str] = None,
    ) -> ProjectTree:
        """
        Create a new workflow.

        Args:
            project_name: Human-readable project name.
            nodes: List of node definitions (dicts).
            project_id: Optional custom project ID.

        Returns:
            Created ProjectTree.
        """
        if not project_id:
            project_id = f"proj_{uuid.uuid4().hex[:8]}"

        now = datetime.now(timezone.utc).isoformat()

        workflow_nodes = []
        for node_def in nodes:
            conditions = []
            for cond in node_def.get("target_conditions", []):
                conditions.append(TargetCondition(**cond))

            node = WorkflowNode(
                node_id=node_def.get("node_id", f"node_{uuid.uuid4().hex[:6]}"),
                task_title=node_def.get("task_title", "Untitled"),
                execution_tier=node_def.get("execution_tier", "local"),
                dependencies=node_def.get("dependencies", []),
                target_conditions=conditions,
                agent=node_def.get("agent"),
                tool=node_def.get("tool"),
            )
            workflow_nodes.append(node)

        workflow = ProjectTree(
            project_id=project_id,
            project_name=project_name,
            project_tree=workflow_nodes,
            created_at=now,
            updated_at=now,
        )

        self._update_global_status(workflow)
        self.save_workflow(workflow)

        return workflow

    def load_workflow(self, project_id: str) -> Optional[ProjectTree]:
        """
        Load a workflow from disk.

        Args:
            project_id: Project ID to load.

        Returns:
            ProjectTree or None.
        """
        path = os.path.join(self.workflows_dir, "plan.json")
        if not os.path.exists(path):
            return None

        with open(path, "r") as f:
            data = json.load(f)

        return ProjectTree(**data)

    def save_workflow(self, workflow: ProjectTree) -> str:
        """
        Save a workflow to disk.

        Args:
            workflow: ProjectTree to save.

        Returns:
            Path to saved file.
        """
        workflow.updated_at = datetime.now(timezone.utc).isoformat()
        path = os.path.join(self.workflows_dir, "plan.json")

        with open(path, "w") as f:
            json.dump(workflow.model_dump(), f, indent=2, default=str)

        return path

    def find_next_pending(self, workflow: ProjectTree) -> Optional[WorkflowNode]:
        """
        Find the next pending node whose dependencies are all satisfied.

        Args:
            workflow: The workflow to search.

        Returns:
            Next executable WorkflowNode or None.
        """
        completed_ids = {
            n.node_id for n in workflow.project_tree
            if n.status == "completed"
        }

        for node in workflow.project_tree:
            if node.status != "pending":
                continue

            # Check all dependencies are completed
            deps_met = all(dep in completed_ids for dep in node.dependencies)
            if deps_met:
                return node

        return None

    def update_node(
        self,
        workflow: ProjectTree,
        node_id: str,
        status: str,
        result: Any = None,
        error: Optional[str] = None,
    ) -> bool:
        """
        Update a node's status and result.

        Args:
            workflow: The workflow containing the node.
            node_id: Node ID to update.
            status: New status (pending, in_progress, completed, failed).
            result: Optional result data.
            error: Optional error message.

        Returns:
            True if updated successfully.
        """
        for node in workflow.project_tree:
            if node.node_id == node_id:
                node.status = status
                now = datetime.now(timezone.utc).isoformat()

                if status == "in_progress":
                    node.timestamps["started_at"] = now
                    node.completion = 50.0
                elif status == "completed":
                    node.timestamps["completed_at"] = now
                    node.completion = 100.0
                    node.result = result
                elif status == "failed":
                    node.timestamps["failed_at"] = now
                    node.error = error
                    node.completion = 0.0

                self._update_global_status(workflow)
                return True

        return False

    def _update_global_status(self, workflow: ProjectTree) -> None:
        """Recalculate global workflow status."""
        total = len(workflow.project_tree)
        completed = sum(
            1 for n in workflow.project_tree if n.status == "completed"
        )
        failed = sum(
            1 for n in workflow.project_tree if n.status == "failed"
        )

        workflow.global_status.total_nodes = total
        workflow.global_status.completed_nodes = completed
        workflow.global_status.failed_nodes = failed
        workflow.global_status.completion = (
            (completed / total * 100) if total > 0 else 0
        )

        # Set current node
        for node in workflow.project_tree:
            if node.status == "in_progress":
                workflow.global_status.current_node = node.node_id
                break
        else:
            next_pending = self.find_next_pending(workflow)
            if next_pending:
                workflow.global_status.current_node = next_pending.node_id
            else:
                workflow.global_status.current_node = None

    def list_workflows(self) -> list[dict]:
        """List all saved workflows."""
        workflows = []
        for fname in os.listdir(self.workflows_dir):
            if fname.endswith(".json"):
                path = os.path.join(self.workflows_dir, fname)
                try:
                    with open(path) as f:
                        data = json.load(f)
                    workflows.append({
                        "project_id": data.get("project_id"),
                        "project_name": data.get("project_name"),
                        "completion": data.get("global_status", {}).get("completion", 0),
                        "nodes": len(data.get("project_tree", [])),
                    })
                except Exception:
                    continue
        return workflows

    def execute_workflow(
        self,
        workflow: ProjectTree,
        executor_fn,
        verifier_fn=None,
    ) -> dict:
        """
        Execute a workflow by processing nodes in dependency order.

        Args:
            workflow: The workflow to execute.
            executor_fn: Callable(node) -> result
            verifier_fn: Optional Callable(node, assertions) -> bool

        Returns:
            Execution summary dict.
        """
        executed = 0
        succeeded = 0
        failed = 0

        while True:
            node = self.find_next_pending(workflow)
            if node is None:
                break

            # Mark as in progress
            self.update_node(workflow, node.node_id, "in_progress")
            self.save_workflow(workflow)

            try:
                result = executor_fn(node)

                # Run verification if assertions exist
                verified = True
                if node.target_conditions and verifier_fn:
                    assertions = [
                        {"assertion_type": tc.assertion_type, "target": tc.target}
                        for tc in node.target_conditions
                    ]
                    verified = verifier_fn(node, assertions)

                if verified:
                    self.update_node(workflow, node.node_id, "completed", result=result)
                    succeeded += 1
                else:
                    self.update_node(workflow, node.node_id, "failed", error="Verification failed")
                    failed += 1

            except Exception as e:
                self.update_node(workflow, node.node_id, "failed", error=str(e))
                failed += 1

            executed += 1
            self.save_workflow(workflow)

        return {
            "executed": executed,
            "succeeded": succeeded,
            "failed": failed,
            "completion": workflow.global_status.completion,
        }
