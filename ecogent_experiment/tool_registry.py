"""
Chroma Semantic Tool Registry.

Uses ChromaDB for natural-language tool retrieval. Tools are stored
with semantic descriptions for similarity-based lookup.

Chroma stores the semantic registry/reference.
Actual implementation lives in the filesystem.
"""

import json
import os
from typing import Any, Optional

try:
    import chromadb
except ImportError:
    chromadb = None


# ============================================================
# Tool Registry
# ============================================================


class ToolRegistry:
    """
    Semantic tool registry backed by ChromaDB.

    Collections:
    - builtin_tools: Permanent built-in tools
    - generated_tools: Dynamically created tools
    - project_tools: Project-specific tools
    - workflow_memory: Workflow execution memory
    """

    COLLECTIONS = ["builtin_tools", "generated_tools", "project_tools", "workflow_memory", "browser_patterns"]

    def __init__(self, chroma_dir: str):
        """
        Initialize the tool registry.

        Args:
            chroma_dir: Path to ChromaDB persistent storage.
        """
        if chromadb is None:
            raise ImportError("chromadb is required. Run: pip install chromadb")

        self.chroma_dir = os.path.abspath(chroma_dir)
        self.client = chromadb.PersistentClient(path=self.chroma_dir)
        self._collections = {}

        # Initialize collections
        for name in self.COLLECTIONS:
            self._collections[name] = self.client.get_or_create_collection(
                name=name,
                metadata={"description": f"Ecogent {name} collection"},
            )

    def register_tool(
        self,
        tool_key: str,
        natural_name: str,
        description: str,
        category: str,
        agent: str,
        execution: str = "local",
        persistent: bool = True,
        collection: str = "builtin_tools",
        extra_metadata: Optional[dict] = None,
    ) -> bool:
        """
        Register a tool in the semantic registry.

        Args:
            tool_key: Unique tool identifier.
            natural_name: Human-readable tool name.
            description: Natural language description for semantic search.
            category: Tool category (filesystem, data, system, testing).
            agent: Agent that handles this tool.
            execution: Execution tier (local, cloud).
            persistent: Whether the tool is permanent.
            collection: Target collection name.
            extra_metadata: Additional metadata to store.

        Returns:
            True if registered successfully.
        """
        if collection not in self._collections:
            return False

        coll = self._collections[collection]
        metadata = {
            "natural_name": natural_name,
            "category": category,
            "agent": agent,
            "execution": execution,
            "persistent": persistent,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        # Upsert (add or update)
        try:
            existing = coll.get(ids=[tool_key])
            if existing and existing["ids"]:
                coll.update(
                    ids=[tool_key],
                    documents=[description],
                    metadatas=[metadata],
                )
            else:
                coll.add(
                    ids=[tool_key],
                    documents=[description],
                    metadatas=[metadata],
                )
            return True
        except Exception:
            try:
                coll.add(
                    ids=[tool_key],
                    documents=[description],
                    metadatas=[metadata],
                )
                return True
            except Exception:
                return False

    def query_tools(
        self,
        query: str,
        n_results: int = 5,
        collection: str = "builtin_tools",
        category: Optional[str] = None,
    ) -> list[dict]:
        """
        Query tools using natural language semantic search.

        Args:
            query: Natural language query (e.g., "change the name of this file").
            n_results: Maximum number of results.
            collection: Collection to search.
            category: Optional category filter.

        Returns:
            List of matching tool dicts with scores.
        """
        if collection not in self._collections:
            return []

        coll = self._collections[collection]

        where = None
        if category:
            where = {"category": category}

        try:
            results = coll.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
            )
        except Exception:
            return []

        tools = []
        if results and results["ids"] and results["ids"][0]:
            for i, tool_id in enumerate(results["ids"][0]):
                tool = {
                    "tool_key": tool_id,
                    "description": results["documents"][0][i] if results["documents"] else "",
                    "distance": results["distances"][0][i] if results.get("distances") else 0,
                }
                if results.get("metadatas") and results["metadatas"][0]:
                    tool.update(results["metadatas"][0][i])
                tools.append(tool)

        return tools

    def get_tool(self, tool_key: str, collection: str = "builtin_tools") -> Optional[dict]:
        """
        Get a specific tool by key.

        Args:
            tool_key: Tool identifier.
            collection: Collection to search.

        Returns:
            Tool dict or None.
        """
        if collection not in self._collections:
            return None

        coll = self._collections[collection]
        try:
            result = coll.get(ids=[tool_key])
            if result and result["ids"]:
                tool = {
                    "tool_key": result["ids"][0],
                    "description": result["documents"][0] if result["documents"] else "",
                }
                if result.get("metadatas") and result["metadatas"]:
                    tool.update(result["metadatas"][0])
                return tool
        except Exception:
            pass
        return None

    def deregister_tool(self, tool_key: str, collection: str = "generated_tools") -> bool:
        """
        Remove a tool from the registry.

        Only non-persistent (generated) tools can be deregistered.

        Args:
            tool_key: Tool identifier.
            collection: Collection to remove from.

        Returns:
            True if removed.
        """
        if collection not in self._collections:
            return False

        # Don't allow deleting persistent built-in tools
        if collection == "builtin_tools":
            tool = self.get_tool(tool_key, collection)
            if tool and tool.get("persistent", True):
                return False

        try:
            self._collections[collection].delete(ids=[tool_key])
            return True
        except Exception:
            return False

    def deregister_project_tools(self, project_id: str, collection: str = "project_tools") -> int:
        """
        Remove all tools belonging to a specific project.
        """
        if collection not in self._collections:
            return 0
            
        coll = self._collections[collection]
        try:
            results = coll.get(where={"project_id": project_id})
            if results and results.get("ids"):
                ids_to_delete = results["ids"]
                coll.delete(ids=ids_to_delete)
                return len(ids_to_delete)
        except Exception:
            pass
        return 0

    def list_tools(self, collection: str = "builtin_tools") -> list[dict]:
        """
        List all tools in a collection.

        Args:
            collection: Collection to list.

        Returns:
            List of tool dicts.
        """
        if collection not in self._collections:
            return []

        coll = self._collections[collection]
        try:
            result = coll.get()
            tools = []
            if result and result["ids"]:
                for i, tool_id in enumerate(result["ids"]):
                    tool = {
                        "tool_key": tool_id,
                        "description": result["documents"][i] if result["documents"] else "",
                    }
                    if result.get("metadatas") and result["metadatas"]:
                        tool.update(result["metadatas"][i])
                    tools.append(tool)
            return tools
        except Exception:
            return []

    def search_all_collections(self, query: str, n_results: int = 5) -> list[dict]:
        """
        Search across all collections for matching tools.

        Args:
            query: Natural language query.
            n_results: Max results per collection.

        Returns:
            Combined list of matching tools.
        """
        all_results = []
        for collection_name in ["builtin_tools", "generated_tools", "project_tools"]:
            results = self.query_tools(query, n_results, collection_name)
            for tool in results:
                tool["source_collection"] = collection_name
            all_results.extend(results)

        # Sort by distance (lower is better)
        all_results.sort(key=lambda t: t.get("distance", float("inf")))
        return all_results[:n_results]

    def save_workflow_memory(self, project_id: str, original_task: str, plan_json: str) -> bool:
        """Save a generated workflow plan to memory for future reuse."""
        if "workflow_memory" not in self._collections:
            return False
            
        coll = self._collections["workflow_memory"]
        try:
            coll.add(
                ids=[project_id],
                documents=[original_task],  # Embed the user's natural language task description
                metadatas=[{"plan_json": plan_json}]
            )
            return True
        except Exception:
            # If it already exists, update it
            try:
                coll.update(
                    ids=[project_id],
                    documents=[original_task],
                    metadatas=[{"plan_json": plan_json}]
                )
                return True
            except Exception:
                return False

    def query_workflow_memory(self, task_query: str, n_results: int = 1) -> list[dict]:
        """Search for similar past workflows."""
        if "workflow_memory" not in self._collections:
            return []
            
        coll = self._collections["workflow_memory"]
        try:
            results = coll.query(
                query_texts=[task_query],
                n_results=n_results
            )
            
            workflows = []
            if results and results["ids"] and results["ids"][0]:
                for i, proj_id in enumerate(results["ids"][0]):
                    wf = {
                        "project_id": proj_id,
                        "original_task": results["documents"][0][i] if results["documents"] else "",
                        "distance": results["distances"][0][i] if results.get("distances") else 0,
                    }
                    if results.get("metadatas") and results["metadatas"][0]:
                        wf.update(results["metadatas"][0][i])
                    workflows.append(wf)
            return workflows
        except Exception:
            return []

    def get_stats(self) -> dict:
        """Get registry statistics."""
        stats = {}
        for name, coll in self._collections.items():
            try:
                stats[name] = coll.count()
            except Exception:
                stats[name] = 0
        return stats
