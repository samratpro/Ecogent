"""
Built-in Testing Tools.

Deterministic Python functions for testing and verification.
"""

import os
import subprocess
import sys


def run_python_test(test_path: str, verbose: bool = True) -> dict:
    """
    Run Python unit tests using pytest.

    Args:
        test_path: Path to test file or directory.
        verbose: Whether to use verbose output.

    Returns:
        Dict with 'success', 'output', 'exit_code'.
    """
    test_path = os.path.abspath(test_path)

    if not os.path.exists(test_path):
        return {"success": False, "error": f"Test path not found: {test_path}"}

    try:
        cmd = [sys.executable, "-m", "pytest", test_path]
        if verbose:
            cmd.append("-v")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "test_path": test_path,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Tests timed out (>300s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def verify_file(
    path: str,
    should_exist: bool = True,
    min_size: int = 0,
    contains: str = None,
) -> dict:
    """
    Verify that a file exists and optionally check its content.

    Args:
        path: Path to the file.
        should_exist: Whether the file should exist.
        min_size: Minimum file size in bytes.
        contains: Optional text that should be in the file.

    Returns:
        Dict with 'success', 'checks' list.
    """
    path = os.path.abspath(path)
    checks = []
    all_passed = True

    # Existence check
    exists = os.path.exists(path) and os.path.isfile(path)
    existence_ok = exists == should_exist
    checks.append({
        "check": "exists" if should_exist else "not_exists",
        "passed": existence_ok,
        "actual": exists,
    })
    if not existence_ok:
        all_passed = False

    if exists and should_exist:
        # Size check
        size = os.path.getsize(path)
        size_ok = size >= min_size
        checks.append({
            "check": "min_size",
            "passed": size_ok,
            "expected_min": min_size,
            "actual": size,
        })
        if not size_ok:
            all_passed = False

        # Content check
        if contains:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                content_ok = contains in content
                checks.append({
                    "check": "contains",
                    "passed": content_ok,
                    "pattern": contains,
                })
                if not content_ok:
                    all_passed = False
            except Exception as e:
                checks.append({
                    "check": "contains",
                    "passed": False,
                    "error": str(e),
                })
                all_passed = False

    return {
        "success": all_passed,
        "path": path,
        "checks": checks,
    }


def verify_directory(
    path: str,
    should_exist: bool = True,
    min_files: int = 0,
    contains_file: str = None,
) -> dict:
    """
    Verify that a directory exists and optionally check its contents.

    Args:
        path: Path to the directory.
        should_exist: Whether the directory should exist.
        min_files: Minimum number of files in the directory.
        contains_file: A specific filename that should be present.

    Returns:
        Dict with 'success', 'checks' list.
    """
    path = os.path.abspath(path)
    checks = []
    all_passed = True

    # Existence check
    exists = os.path.exists(path) and os.path.isdir(path)
    existence_ok = exists == should_exist
    checks.append({
        "check": "exists" if should_exist else "not_exists",
        "passed": existence_ok,
        "actual": exists,
    })
    if not existence_ok:
        all_passed = False

    if exists and should_exist:
        entries = os.listdir(path)
        files = [e for e in entries if os.path.isfile(os.path.join(path, e))]

        # Min files check
        if min_files > 0:
            files_ok = len(files) >= min_files
            checks.append({
                "check": "min_files",
                "passed": files_ok,
                "expected_min": min_files,
                "actual": len(files),
            })
            if not files_ok:
                all_passed = False

        # Contains file check
        if contains_file:
            has_file = contains_file in entries
            checks.append({
                "check": "contains_file",
                "passed": has_file,
                "expected": contains_file,
            })
            if not has_file:
                all_passed = False

    return {
        "success": all_passed,
        "path": path,
        "checks": checks,
    }
