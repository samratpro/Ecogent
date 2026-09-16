"""
Built-in Shell Tools.

Deterministic Python functions for executing shell commands.
"""

import subprocess
from typing import Optional

def run_shell_command(command: Optional[str] = None, task: Optional[str] = None, input_text: Optional[str] = None) -> dict:
    """
    Execute a shell command.

    Args:
        command: The shell command to execute.
        task: Natural language task to extract command from if missing.
        input_text: Optional text to pipe into standard input (stdin).

    Returns:
        Dict with execution results (stdout, stderr, exit_code).
    """
    cmd = command or task
    if not cmd:
        return {"success": False, "error": "No command provided."}
        
    try:
        import os
        import signal
        is_windows = os.name == 'nt'
        
        # We pass `input=input_text or ""` so that if the script tries to read from stdin 
        # unexpectedly, it gets an EOF and crashes immediately instead of freezing the CLI!
        result = subprocess.run(
            cmd,
            input=input_text or "",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 10 seconds (likely waiting for input). Consider passing 'input_text'."}
    except Exception as e:
        return {"success": False, "error": f"Failed to execute command: {str(e)}"}
