"""
Built-in Code Tools.

Deterministic Python functions for code manipulation, linting, and formatting.
"""

import ast
from typing import Optional

def lint_code(code: Optional[str] = None, task: Optional[str] = None) -> dict:
    """
    Check Python code for syntax errors.

    Args:
        code: Python source code string.
        task: Natural language task containing code if 'code' is missing.

    Returns:
        Dict with linting results.
    """
    source = code or task
    if not source:
        return {"success": False, "error": "No code provided to lint."}
        
    try:
        ast.parse(source)
        return {"success": True, "message": "No syntax errors found."}
    except SyntaxError as e:
        return {"success": False, "error": f"SyntaxError: {e.msg} at line {e.lineno}"}
    except Exception as e:
        return {"success": False, "error": f"Error parsing code: {str(e)}"}

def format_code(code: Optional[str] = None, task: Optional[str] = None) -> dict:
    """
    Format Python code. Fallback simple formatter if tools like black are absent.

    Args:
        code: Python source code string.
        task: Natural language task containing code if 'code' is missing.

    Returns:
        Dict with formatted code.
    """
    source = code or task
    if not source:
        return {"success": False, "error": "No code provided to format."}
        
    # In a real scenario, this would call `black` or `autopep8`.
    # For now, we just ensure it compiles by AST.
    try:
        parsed = ast.parse(source)
        # unparse is available in python 3.9+
        formatted = ast.unparse(parsed)
        return {"success": True, "formatted_code": formatted}
    except Exception as e:
        return {"success": False, "error": f"Could not format code. {str(e)}"}


def run_python_inline(code: str) -> dict:
    """
    Run arbitrary python code inline and return the captured output.
    
    Args:
        code: Python source code string to execute.
        
    Returns:
        Dict with 'success' and 'output' or 'error'.
    """
    import io
    import sys
    
    if not code:
        return {"success": False, "error": "No code provided to execute."}
        
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected_output = sys.stdout = io.StringIO()
    redirected_error = sys.stderr = io.StringIO()
    
    try:
        # Wrap in a try-except to catch execution errors
        exec(code, globals(), locals())
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        return {
            "success": True, 
            "output": redirected_output.getvalue(),
            "error_output": redirected_error.getvalue()
        }
    except Exception as e:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        return {
            "success": False, 
            "error": str(e),
            "output": redirected_output.getvalue(),
            "error_output": redirected_error.getvalue()
        }
