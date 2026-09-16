"""
Browser Workflow Manager.

The single entry point for browser automation tasks.
Decides whether to REPLAY an existing pattern or RECORD a new one.

Usage:
    manager = BrowserWorkflowManager(
        project_id=project_id,
        chroma_dir=chroma_dir,
        projects_dir=projects_dir,
        cloud_provider=cloud_provider,
    )
    result = manager.run(task, variables={})
"""

import os
from typing import Dict, Optional

from ecogent_experiment.browser_workflow.pattern_store import BrowserPatternStore
from ecogent_experiment.browser_workflow.recorder import BrowserRecordingAgent
from ecogent_experiment.browser_workflow.replayer import BrowserReplayEngine
from ecogent_experiment.browser_workflow.schema import BrowserReplayResult


class BrowserWorkflowManager:
    """
    Orchestrates browser automation: decides replay vs. recording.

    Decision logic:
      1. Query BrowserPatternStore (Chroma) for a matching pattern.
      2. Match found (distance < 0.35) → BrowserReplayEngine.replay()
      3. No match → BrowserRecordingAgent.record_and_execute()
    """

    def __init__(
        self,
        project_id: str,
        chroma_dir: str,
        projects_dir: str,
        cloud_provider=None,
        headless: bool = False,
        screenshots_dir: Optional[str] = None,
    ):
        self.project_id = project_id
        self.cloud_provider = cloud_provider

        self.pattern_store = BrowserPatternStore(
            chroma_dir=chroma_dir,
            projects_dir=projects_dir,
            project_id=project_id,
        )

        self._headless = headless
        self._screenshots_dir = screenshots_dir

    def run(
        self,
        task: str,
        variables: Optional[Dict[str, str]] = None,
        console=None,
    ) -> BrowserReplayResult:
        """
        Execute a browser automation task.

        Args:
            task:      Natural-language task description.
            variables: Dynamic values to substitute (e.g. {"query": "laptops"}).
            console:   Optional Rich console for progress output.

        Returns:
            BrowserReplayResult (mode="replay" or mode="recording").
        """
        variables = variables or {}

        # 1. Check for existing pattern
        pattern_meta = self.pattern_store.find_pattern(task)

        if pattern_meta:
            # ── REPLAY PATH ───────────────────────────────────────────
            pattern = self.pattern_store.get_pattern(pattern_meta)
            if pattern:
                if console:
                    console.print(
                        f"  [green]✓ Chroma [browser_patterns]:[/green] "
                        f"Pattern [cyan]{pattern_meta['pattern_id']}[/cyan] matched "
                        f"(distance: {pattern_meta.get('distance', 0):.2f})"
                    )
                replayer = BrowserReplayEngine(
                    cloud_provider=self.cloud_provider,
                    headless=self._headless,
                )
                return replayer.replay(
                    pattern=pattern,
                    pattern_store=self.pattern_store,
                    variables=variables,
                    console=console,
                )

        # ── RECORDING PATH ────────────────────────────────────────────
        if console:
            console.print(
                f"  [dim]✓ Chroma [browser_patterns]: No matching pattern found. "
                f"Starting recording...[/dim]"
            )

        recorder = BrowserRecordingAgent(
            pattern_store=self.pattern_store,
            cloud_provider=self.cloud_provider,
            headless=self._headless,
            screenshots_dir=self._screenshots_dir,
        )
        return recorder.record_and_execute(
            task=task,
            variables=variables,
            console=console,
        )

    def get_pattern_hint(self, task: str) -> Optional[str]:
        """
        Check if a pattern exists and return an LLM hint string.

        Used when the Supervisor fails to detect intent — inject this
        hint into the cloud prompt so the LLM never regenerates a plan.

        Returns:
            Hint string if pattern exists, None otherwise.
        """
        pattern_meta = self.pattern_store.find_pattern(task)
        if pattern_meta:
            return self.pattern_store.build_pattern_hint(pattern_meta)
        return None

    def list_patterns(self) -> list[dict]:
        """List all recorded patterns for this project."""
        return self.pattern_store.list_project_patterns()
