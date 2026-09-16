"""
Browser Automation Tool.

Builtin tool function for multi-step browser automation tasks.
Registered as 'browser_task' in ChromaDB and LangChain tool list.

This is the glue layer between the LangChain tool system and the
BrowserWorkflowManager. All routing (replay vs. record) happens inside
the manager.

Returns a standard tool result dict compatible with EcogentTool._run().
"""

import os
import sys
from typing import Any, Callable, Dict, Optional

# Ensure project root on path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def browser_task(
    task: str = "",
    project_id: str = "",
    variables: Optional[Dict[str, Any]] = None,
    ask_llm: Optional[Callable] = None,
    cloud_provider=None,
    chroma_dir: str = "",
    projects_dir: str = "",
    headless: bool = True,
    console=None,
    **kwargs,
) -> dict:
    """
    Execute a multi-step browser automation task.

    On first run: communicates with the cloud LLM step-by-step to record
    a reusable workflow pattern (saved to ChromaDB + disk JSON).

    On subsequent runs with the same type of task: replays the saved
    pattern via Playwright with ZERO cloud AI calls (unless a validation
    step fails, in which case only that step uses AI for recovery).

    Args:
        task:          Natural-language task (e.g. "go to amazon, check laptop prices").
        project_id:    Current Ecogent project ID (patterns are project-scoped).
        variables:     Dynamic values to substitute in pattern (e.g. {"query": "laptops"}).
        ask_llm:       LLM callback (used as cloud_provider fallback if no provider).
        cloud_provider: Ecogent cloud provider instance.
        chroma_dir:    Path to ChromaDB storage.
        projects_dir:  Path to projects/ directory.
        headless:      Run browser headlessly (default True).
        console:       Rich console for progress output.

    Returns:
        dict with keys: success, mode, cloud_calls, ai_recovery_count,
                        extracted_data, preview
    """
    if not task:
        return {
            "success": False,
            "error": "No task provided to browser_task tool.",
            "preview": "Error: No task provided.",
        }

    # Resolve paths
    if not chroma_dir:
        chroma_dir = os.path.join(_PROJECT_ROOT, "data", "chroma")
    if not projects_dir:
        projects_dir = os.path.join(_PROJECT_ROOT, "projects")

    # Validate Playwright availability
    try:
        import playwright  # noqa: F401
    except ImportError:
        return {
            "success": False,
            "error": (
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            ),
            "preview": "Error: Playwright not installed.",
        }

    # Import manager here to avoid circular imports
    from ecogent_experiment.browser_workflow.manager import BrowserWorkflowManager

    manager = BrowserWorkflowManager(
        project_id=project_id or "default",
        chroma_dir=chroma_dir,
        projects_dir=projects_dir,
        cloud_provider=cloud_provider,
        headless=headless,
    )

    result = manager.run(
        task=task,
        variables=variables or {},
        console=console,
    )

    # Build preview string (first 500 chars of summary for tool output)
    preview = result.summary[:500] if result.summary else (
        f"Browser task {'completed' if result.success else 'failed'}. "
        f"Mode: {result.mode}. Cloud calls: {result.cloud_calls}."
    )

    return {
        "success":            result.success,
        "mode":               result.mode,
        "pattern_id":         result.pattern_id,
        "cloud_calls":        result.cloud_calls,
        "ai_recovery_count":  result.cloud_recovery_count,
        "extracted_data":     result.extracted_data,
        "preview":            preview,
        "error":              result.error,
    }
