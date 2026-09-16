"""
Verification Engine.

Deterministic assertion-based verification for workflow tasks.
Assertions are the primary verification method; Tiny LLM assists
only with interpreting ambiguous results.
"""

import csv
import os
import subprocess
import sys
from typing import Any, Optional


# ============================================================
# Assertion Types
# ============================================================

ASSERTION_TYPES = {
    "FILE_EXISTS",
    "FILE_NOT_EXISTS",
    "FILE_MIN_SIZE",
    "DIRECTORY_EXISTS",
    "CSV_COLUMN_EXISTS",
    "CSV_ROW_COUNT",
    "COMMAND_EXIT_CODE",
    "TEXT_CONTAINS",
}


def verify_assertion(assertion: dict) -> dict:
    """
    Run a single deterministic assertion.

    Args:
        assertion: Dict with 'assertion_type' and 'target'.

    Returns:
        Dict with 'passed' (bool), 'message' (str), 'details' (dict).
    """
    assertion_type = assertion.get("assertion_type", "")
    target = assertion.get("target", "")

    if assertion_type not in ASSERTION_TYPES:
        return {
            "passed": False,
            "message": f"Unknown assertion type: {assertion_type}",
            "details": {"assertion_type": assertion_type},
        }

    handlers = {
        "FILE_EXISTS": _assert_file_exists,
        "FILE_NOT_EXISTS": _assert_file_not_exists,
        "FILE_MIN_SIZE": _assert_file_min_size,
        "DIRECTORY_EXISTS": _assert_directory_exists,
        "CSV_COLUMN_EXISTS": _assert_csv_column_exists,
        "CSV_ROW_COUNT": _assert_csv_row_count,
        "COMMAND_EXIT_CODE": _assert_command_exit_code,
        "TEXT_CONTAINS": _assert_text_contains,
    }

    handler = handlers[assertion_type]
    return handler(target)


def verify_all(assertions: list[dict]) -> dict:
    """
    Run multiple assertions and return aggregate results.

    Args:
        assertions: List of assertion dicts.

    Returns:
        Dict with 'all_passed', 'total', 'passed', 'failed', 'results'.
    """
    results = []
    passed_count = 0
    failed_count = 0

    for assertion in assertions:
        result = verify_assertion(assertion)
        results.append({
            "assertion": assertion,
            **result,
        })
        if result["passed"]:
            passed_count += 1
        else:
            failed_count += 1

    return {
        "all_passed": failed_count == 0,
        "total": len(assertions),
        "passed": passed_count,
        "failed": failed_count,
        "results": results,
    }


# ============================================================
# Assertion Handlers
# ============================================================


def _assert_file_exists(target: Any) -> dict:
    """Assert that a file exists."""
    path = _get_path(target)
    exists = os.path.exists(path) and os.path.isfile(path)
    return {
        "passed": exists,
        "message": f"File {'exists' if exists else 'not found'}: {path}",
        "details": {"path": path, "exists": exists},
    }


def _assert_file_not_exists(target: Any) -> dict:
    """Assert that a file does not exist."""
    path = _get_path(target)
    not_exists = not os.path.exists(path)
    return {
        "passed": not_exists,
        "message": f"File {'does not exist' if not_exists else 'still exists'}: {path}",
        "details": {"path": path, "exists": not not_exists},
    }


def _assert_file_min_size(target: Any) -> dict:
    """Assert that a file meets a minimum size."""
    if isinstance(target, dict):
        path = target.get("file_path", target.get("path", ""))
        min_size = target.get("min_size", 0)
    else:
        return {"passed": False, "message": "Invalid target for FILE_MIN_SIZE", "details": {}}

    path = os.path.abspath(path)

    if not os.path.exists(path):
        return {
            "passed": False,
            "message": f"File not found: {path}",
            "details": {"path": path, "min_size": min_size},
        }

    actual_size = os.path.getsize(path)
    passed = actual_size >= min_size

    return {
        "passed": passed,
        "message": f"File size {actual_size} {'>=>' if passed else '<'} {min_size}",
        "details": {"path": path, "actual_size": actual_size, "min_size": min_size},
    }


def _assert_directory_exists(target: Any) -> dict:
    """Assert that a directory exists."""
    path = _get_path(target)
    exists = os.path.exists(path) and os.path.isdir(path)
    return {
        "passed": exists,
        "message": f"Directory {'exists' if exists else 'not found'}: {path}",
        "details": {"path": path, "exists": exists},
    }


def _assert_csv_column_exists(target: Any) -> dict:
    """Assert that a column exists in a CSV file."""
    if isinstance(target, dict):
        path = target.get("file_path", target.get("path", ""))
        column_name = target.get("column_name", target.get("column", ""))
    else:
        return {"passed": False, "message": "Invalid target for CSV_COLUMN_EXISTS", "details": {}}

    path = os.path.abspath(path)

    if not os.path.exists(path):
        return {
            "passed": False,
            "message": f"CSV file not found: {path}",
            "details": {"path": path, "column": column_name},
        }

    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            headers = next(reader, [])

        found = column_name in headers
        return {
            "passed": found,
            "message": f"Column '{column_name}' {'found' if found else 'not found'} in {path}",
            "details": {
                "path": path,
                "column": column_name,
                "available_columns": headers,
            },
        }
    except Exception as e:
        return {"passed": False, "message": str(e), "details": {"path": path}}


def _assert_csv_row_count(target: Any) -> dict:
    """Assert that a CSV has a minimum number of rows."""
    if isinstance(target, dict):
        path = target.get("file_path", target.get("path", ""))
        min_rows = target.get("min_rows", target.get("row_count", 0))
        exact_rows = target.get("exact_rows", None)
    else:
        return {"passed": False, "message": "Invalid target for CSV_ROW_COUNT", "details": {}}

    path = os.path.abspath(path)

    if not os.path.exists(path):
        return {
            "passed": False,
            "message": f"CSV file not found: {path}",
            "details": {"path": path},
        }

    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            row_count = sum(1 for _ in reader)

        if exact_rows is not None:
            passed = row_count == exact_rows
            message = f"Row count {row_count} {'==' if passed else '!='} {exact_rows}"
        else:
            passed = row_count >= min_rows
            message = f"Row count {row_count} {'>=' if passed else '<'} {min_rows}"

        return {
            "passed": passed,
            "message": message,
            "details": {"path": path, "actual_rows": row_count},
        }
    except Exception as e:
        return {"passed": False, "message": str(e), "details": {"path": path}}


def _assert_command_exit_code(target: Any) -> dict:
    """Assert that a command exits with a specific code."""
    if isinstance(target, dict):
        command = target.get("command", "")
        expected_code = target.get("exit_code", 0)
    else:
        return {"passed": False, "message": "Invalid target for COMMAND_EXIT_CODE", "details": {}}

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        passed = result.returncode == expected_code
        return {
            "passed": passed,
            "message": f"Exit code {result.returncode} {'==' if passed else '!='} {expected_code}",
            "details": {
                "command": command,
                "actual_code": result.returncode,
                "expected_code": expected_code,
                "stdout": result.stdout[:200],
                "stderr": result.stderr[:200],
            },
        }
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "message": "Command timed out",
            "details": {"command": command},
        }
    except Exception as e:
        return {"passed": False, "message": str(e), "details": {"command": command}}


def _assert_text_contains(target: Any) -> dict:
    """Assert that a file contains specific text."""
    if isinstance(target, dict):
        path = target.get("file_path", target.get("path", ""))
        text = target.get("text", target.get("contains", ""))
    else:
        return {"passed": False, "message": "Invalid target for TEXT_CONTAINS", "details": {}}

    path = os.path.abspath(path)

    if not os.path.exists(path):
        return {
            "passed": False,
            "message": f"File not found: {path}",
            "details": {"path": path, "text": text},
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        found = text in content
        return {
            "passed": found,
            "message": f"Text '{text[:50]}' {'found' if found else 'not found'} in {path}",
            "details": {"path": path, "text": text, "found": found},
        }
    except Exception as e:
        return {"passed": False, "message": str(e), "details": {"path": path}}


# ============================================================
# Helpers
# ============================================================


def _get_path(target: Any) -> str:
    """Extract and normalize a path from a target value."""
    if isinstance(target, dict):
        path = target.get("file_path", target.get("path", target.get("target", "")))
    else:
        path = str(target)
    return os.path.abspath(path)
