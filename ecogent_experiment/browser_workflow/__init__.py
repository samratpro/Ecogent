"""
Browser Workflow Package.

Provides pattern-based browser automation with:
- Automatic workflow recording on first run (step-by-step with LLM)
- Zero-AI replay on subsequent runs
- AI recovery only when a validation step fails
- ChromaDB-backed pattern storage for semantic retrieval
"""

from ecogent_experiment.browser_workflow.manager import BrowserWorkflowManager
from ecogent_experiment.browser_workflow.pattern_store import BrowserPatternStore
from ecogent_experiment.browser_workflow.schema import (
    BrowserAction,
    BrowserPattern,
    BrowserReplayResult,
    BrowserStep,
    StepValidation,
)

__all__ = [
    "BrowserWorkflowManager",
    "BrowserPatternStore",
    "BrowserAction",
    "BrowserPattern",
    "BrowserReplayResult",
    "BrowserStep",
    "StepValidation",
]
