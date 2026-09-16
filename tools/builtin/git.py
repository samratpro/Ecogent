"""
Built-in Git Tools.

Deterministic Python functions for interacting with Git repositories.
"""

import subprocess
import os
from typing import Optional

def _run_git_cmd(args: list[str]) -> dict:
    """Helper to run a git command and return standardized output."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=15
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "exit_code": result.returncode
        }
    except FileNotFoundError:
        return {"success": False, "error": "Git executable not found in PATH."}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Git command timed out."}
    except Exception as e:
        return {"success": False, "error": f"Failed to execute git command: {str(e)}"}

def git_status(task: Optional[str] = None) -> dict:
    """
    Get the status of the current git repository.

    Args:
        task: Natural language task (ignored but accepted for signature compatibility).

    Returns:
        Dict with the git status output.
    """
    if not os.path.isdir(".git"):
        return {"success": False, "error": "Not a git repository (or any of the parent directories)."}
        
    return _run_git_cmd(["git", "status", "-s"])

def git_diff(task: Optional[str] = None) -> dict:
    """
    Get the diff of uncommitted changes.

    Args:
        task: Natural language task (ignored but accepted for signature compatibility).

    Returns:
        Dict with the git diff output.
    """
    if not os.path.isdir(".git"):
        return {"success": False, "error": "Not a git repository (or any of the parent directories)."}
        
    return _run_git_cmd(["git", "diff"])

def git_commit(message: Optional[str] = None, task: Optional[str] = None) -> dict:
    """
    Commit all tracked changes with a given message.

    Args:
        message: The commit message.
        task: Natural language task containing commit message if 'message' is missing.

    Returns:
        Dict with the commit results.
    """
    if not os.path.isdir(".git"):
        return {"success": False, "error": "Not a git repository (or any of the parent directories)."}
        
    msg = message or task
    if not msg:
        return {"success": False, "error": "No commit message provided."}
        
    # First add all tracked changes
    add_result = _run_git_cmd(["git", "add", "-u"])
    if not add_result["success"]:
        return {"success": False, "error": f"Failed to stage changes: {add_result.get('stderr')}"}
        
    return _run_git_cmd(["git", "commit", "-m", msg])
