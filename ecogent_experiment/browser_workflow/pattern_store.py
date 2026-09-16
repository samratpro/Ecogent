"""
Browser Pattern Store.

Manages browser workflow patterns in ChromaDB's `browser_patterns` collection.
Provides semantic search, CRUD operations, and disk-based pattern JSON persistence.

Storage layout:
  ChromaDB: browser_patterns collection
    - ID:       bwp_<hash>
    - Document: fingerprint string (for embedding/semantic search)
    - Metadata: project_id, task_summary, url_domain, workflow_file, step_count, etc.

  Disk: projects/<project_id>/browser_workflows/<pattern_id>.json
    - Full BrowserPattern JSON (steps, actions, validations)
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from ecogent_experiment.browser_workflow.fingerprint import (
    extract_url_domain,
    fingerprint_to_id,
    task_to_fingerprint,
)
from ecogent_experiment.browser_workflow.schema import BrowserPattern

try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False


COLLECTION_NAME = "browser_patterns"
MATCH_DISTANCE_THRESHOLD = 0.35  # Chroma distance < this → reuse pattern


class BrowserPatternStore:
    """
    Manages browser workflow patterns in ChromaDB + JSON files on disk.

    All patterns are scoped to a project_id so different projects never
    share or accidentally reuse each other's patterns.
    """

    def __init__(self, chroma_dir: str, projects_dir: str, project_id: str):
        """
        Args:
            chroma_dir:   Path to ChromaDB persistent storage (data/chroma/).
            projects_dir: Path to projects/ directory.
            project_id:   Current project ID (scope for all queries).
        """
        self.chroma_dir = os.path.abspath(chroma_dir)
        self.projects_dir = os.path.abspath(projects_dir)
        self.project_id = project_id
        self._collection = None

        # Create browser_workflows dir for this project
        self._workflows_dir = os.path.join(
            projects_dir, project_id, "browser_workflows"
        )
        os.makedirs(self._workflows_dir, exist_ok=True)

        if _CHROMA_AVAILABLE:
            self._init_collection()

    def _init_collection(self) -> None:
        """Initialize or get the browser_patterns Chroma collection."""
        try:
            client = chromadb.PersistentClient(path=self.chroma_dir)
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"description": "Ecogent browser automation workflow patterns"},
            )
        except Exception as e:
            self._collection = None
            print(f"[BrowserPatternStore] Chroma unavailable: {e}")

    # ------------------------------------------------------------------
    # Find (Semantic Search)
    # ------------------------------------------------------------------

    def find_pattern(self, task: str) -> Optional[dict]:
        """
        Search Chroma for a saved pattern matching this task.

        Filters by project_id so patterns are project-scoped.
        Returns the best match metadata dict, or None if no match.

        The returned dict includes:
          - pattern_id, task_summary, url_domain, workflow_file,
            step_count, run_count, last_run_at, ai_recovery_count
        """
        if not self._collection:
            return self._filesystem_fallback_find(task)

        fingerprint = task_to_fingerprint(task)
        domain = extract_url_domain(task)

        try:
            results = self._collection.query(
                query_texts=[fingerprint],
                n_results=5,
                where={"project_id": self.project_id},
            )
        except Exception:
            return self._filesystem_fallback_find(task)

        if not results or not results["ids"] or not results["ids"][0]:
            return None

        # Find best match below distance threshold
        best = None
        best_dist = float("inf")

        for i, pattern_id in enumerate(results["ids"][0]):
            dist = results["distances"][0][i] if results.get("distances") else 1.0
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}

            if dist >= MATCH_DISTANCE_THRESHOLD:
                continue

            # Prefer same domain if available
            pattern_domain = meta.get("url_domain", "")
            domain_bonus = 0.05 if (domain and domain == pattern_domain) else 0.0
            effective_dist = dist - domain_bonus

            if effective_dist < best_dist:
                best_dist = effective_dist
                best = {
                    "pattern_id": pattern_id,
                    "distance": dist,
                    **meta,
                }

        return best

    def _filesystem_fallback_find(self, task: str) -> Optional[dict]:
        """Fallback: scan the filesystem when Chroma is unavailable."""
        fingerprint = task_to_fingerprint(task)
        pattern_id = fingerprint_to_id(fingerprint)
        json_path = os.path.join(self._workflows_dir, f"{pattern_id}.json")

        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["workflow_file"] = json_path
                return data
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------
    # Load full pattern from disk
    # ------------------------------------------------------------------

    def get_pattern(self, pattern_meta: dict) -> Optional[BrowserPattern]:
        """
        Load the full BrowserPattern from disk using the metadata from find_pattern().

        Args:
            pattern_meta: Dict returned by find_pattern() (contains workflow_file).

        Returns:
            BrowserPattern or None.
        """
        workflow_file = pattern_meta.get("workflow_file", "")

        # Resolve relative paths
        if not os.path.isabs(workflow_file):
            # Try relative to projects_dir
            candidate = os.path.join(self.projects_dir, workflow_file)
            if not os.path.exists(candidate):
                # Try relative to workflows dir
                candidate = os.path.join(self._workflows_dir, workflow_file)
            workflow_file = candidate

        if not os.path.exists(workflow_file):
            return None

        try:
            with open(workflow_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return BrowserPattern(**data)
        except Exception as e:
            print(f"[BrowserPatternStore] Failed to load pattern: {e}")
            return None

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_pattern(self, pattern: BrowserPattern) -> bool:
        """
        Save a BrowserPattern to disk and register it in Chroma.

        Args:
            pattern: Completed BrowserPattern (from recording).

        Returns:
            True if saved successfully.
        """
        # 1. Save JSON to disk
        json_path = os.path.join(self._workflows_dir, f"{pattern.pattern_id}.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(pattern.model_dump(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[BrowserPatternStore] Failed to save JSON: {e}")
            return False

        # 2. Register in Chroma
        if not self._collection:
            return True  # Disk-only fallback

        metadata = {
            "project_id":        pattern.project_id,
            "task_summary":      pattern.task_summary[:200],
            "url_domain":        pattern.url_domain,
            "workflow_file":     json_path,
            "step_count":        len(pattern.steps),
            "run_count":         pattern.run_count,
            "last_run_at":       pattern.last_run_at,
            "ai_recovery_count": pattern.ai_recovery_count,
        }

        try:
            existing = self._collection.get(ids=[pattern.pattern_id])
            if existing and existing["ids"]:
                self._collection.update(
                    ids=[pattern.pattern_id],
                    documents=[pattern.fingerprint],
                    metadatas=[metadata],
                )
            else:
                self._collection.add(
                    ids=[pattern.pattern_id],
                    documents=[pattern.fingerprint],
                    metadatas=[metadata],
                )
            return True
        except Exception as e:
            print(f"[BrowserPatternStore] Chroma save failed: {e}")
            return True  # JSON was saved, so partial success

    # ------------------------------------------------------------------
    # Update (after replay)
    # ------------------------------------------------------------------

    def update_after_replay(self, pattern: BrowserPattern) -> bool:
        """
        Update Chroma metadata + disk JSON after a successful replay.

        Updates: run_count, last_run_at, ai_recovery_count, updated selectors.
        """
        # Re-save full JSON (selectors may have been updated by AI recovery)
        return self.save_pattern(pattern)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_project_patterns(self) -> list[dict]:
        """
        List all patterns for the current project.

        Returns list of metadata dicts for display in CLI.
        """
        if self._collection:
            try:
                results = self._collection.get(
                    where={"project_id": self.project_id}
                )
                patterns = []
                if results and results["ids"]:
                    for i, pid in enumerate(results["ids"]):
                        meta = results["metadatas"][i] if results.get("metadatas") else {}
                        patterns.append({"pattern_id": pid, **meta})
                return patterns
            except Exception:
                pass

        # Filesystem fallback
        patterns = []
        if os.path.exists(self._workflows_dir):
            for fname in os.listdir(self._workflows_dir):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(self._workflows_dir, fname)) as f:
                            data = json.load(f)
                        patterns.append({
                            "pattern_id": data.get("pattern_id", fname),
                            "task_summary": data.get("task_summary", ""),
                            "step_count": len(data.get("steps", [])),
                            "run_count": data.get("run_count", 0),
                            "last_run_at": data.get("last_run_at", ""),
                        })
                    except Exception:
                        continue
        return patterns

    # ------------------------------------------------------------------
    # Build pattern hint for LLM (when pattern exists but supervisor missed it)
    # ------------------------------------------------------------------

    def build_pattern_hint(self, pattern_meta: dict) -> str:
        """
        Build a text hint to inject into the LLM prompt when a pattern
        already exists — so the LLM never regenerates a new plan.

        Args:
            pattern_meta: Dict from find_pattern().

        Returns:
            A prompt string to prepend to the cloud LLM call.
        """
        return (
            f"[SYSTEM NOTE] A recorded browser automation pattern already exists "
            f"for this type of task in this project.\n"
            f"  Pattern ID    : {pattern_meta.get('pattern_id', 'unknown')}\n"
            f"  Summary       : {pattern_meta.get('task_summary', '')}\n"
            f"  Steps recorded: {pattern_meta.get('step_count', '?')}\n"
            f"  Times run     : {pattern_meta.get('run_count', 0)}\n"
            f"  Last run      : {pattern_meta.get('last_run_at', 'never')}\n\n"
            f"DO NOT generate a new browser plan or workflow. "
            f"The pattern will be replayed automatically by the system. "
            f"Simply acknowledge to the user that you will reuse the saved pattern."
        )
