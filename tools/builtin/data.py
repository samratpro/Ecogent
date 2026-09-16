"""
Built-in Data Processing Tools.

Deterministic Python functions for CSV and data operations.
Uses only the Python standard library and numpy (no pandas dependency).
"""

import csv
import json
import os
from typing import Any, Optional

import numpy as np


def read_csv(path: str, encoding: str = "utf-8", max_rows: int = 10000) -> dict:
    """
    Read a CSV file into a list of row dicts.

    Args:
        path: Path to the CSV file.
        encoding: File encoding.
        max_rows: Maximum rows to read.

    Returns:
        Dict with 'success', 'columns', 'rows', 'row_count'.
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {"success": False, "error": f"File not found: {path}"}

    try:
        rows = []
        with open(path, "r", encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames or []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(dict(row))

        return {
            "success": True,
            "path": path,
            "columns": list(columns),
            "rows": rows,
            "row_count": len(rows),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def inspect_csv(path: str, encoding: str = "utf-8") -> dict:
    """
    Inspect the structure, columns, and row count of a CSV file.

    Args:
        path: Path to the CSV file.
        encoding: File encoding.

    Returns:
        Dict with 'success', 'columns', 'row_count', 'sample_values'.
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {"success": False, "error": f"File not found: {path}"}

    try:
        row_count = 0
        columns = []
        sample_rows = []

        with open(path, "r", encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            columns = list(reader.fieldnames or [])
            for i, row in enumerate(reader):
                row_count += 1
                if i < 5:
                    sample_rows.append(dict(row))

        # Detect column types from sample
        column_info = []
        for col in columns:
            values = [r.get(col, "") for r in sample_rows]
            col_type = _detect_type(values)
            column_info.append({
                "name": col,
                "type": col_type,
                "sample": values[:3],
            })

        return {
            "success": True,
            "path": path,
            "columns": columns,
            "column_count": len(columns),
            "row_count": row_count,
            "column_info": column_info,
            "file_size_bytes": os.path.getsize(path),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def calculate_statistics(path: str, column: str, encoding: str = "utf-8") -> dict:
    """
    Calculate statistical measures for a numerical column in a CSV file.

    Args:
        path: Path to the CSV file.
        column: Column name to analyze.
        encoding: File encoding.

    Returns:
        Dict with 'success' and statistical measures.
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {"success": False, "error": f"File not found: {path}"}

    try:
        values = []
        with open(path, "r", encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            if column not in (reader.fieldnames or []):
                return {"success": False, "error": f"Column '{column}' not found"}

            for row in reader:
                try:
                    val = float(row[column])
                    values.append(val)
                except (ValueError, TypeError):
                    pass

        if not values:
            return {"success": False, "error": f"No numeric values in column '{column}'"}

        arr = np.array(values)

        return {
            "success": True,
            "column": column,
            "count": len(values),
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "sum": float(np.sum(arr)),
            "q25": float(np.percentile(arr, 25)),
            "q75": float(np.percentile(arr, 75)),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def filter_dataframe(
    path: str,
    column: str,
    operator: str,
    value: Any,
    encoding: str = "utf-8",
) -> dict:
    """
    Filter rows from a CSV based on a condition.

    Args:
        path: Path to the CSV file.
        column: Column to filter on.
        operator: Comparison operator ('eq', 'ne', 'gt', 'lt', 'gte', 'lte', 'contains').
        value: Value to compare against.
        encoding: File encoding.

    Returns:
        Dict with 'success', 'filtered_rows', 'count'.
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {"success": False, "error": f"File not found: {path}"}

    try:
        filtered = []
        total = 0

        with open(path, "r", encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            if column not in (reader.fieldnames or []):
                return {"success": False, "error": f"Column '{column}' not found"}

            for row in reader:
                total += 1
                cell = row.get(column, "")

                if _compare(cell, operator, value):
                    filtered.append(dict(row))

        return {
            "success": True,
            "total_rows": total,
            "filtered_rows": filtered,
            "filtered_count": len(filtered),
            "column": column,
            "operator": operator,
            "value": value,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def save_csv(path: str, rows: list[dict], encoding: str = "utf-8") -> dict:
    """
    Save data to a CSV file.

    Args:
        path: Output file path.
        rows: List of row dicts to write.
        encoding: File encoding.

    Returns:
        Dict with 'success', 'path', 'row_count'.
    """
    path = os.path.abspath(path)

    if not rows:
        return {"success": False, "error": "No rows to write"}

    try:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        columns = list(rows[0].keys())

        with open(path, "w", encoding=encoding, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

        return {
            "success": True,
            "path": path,
            "row_count": len(rows),
            "columns": columns,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# Helpers
# ============================================================


def _detect_type(values: list[str]) -> str:
    """Detect the likely type of a column from sample values."""
    if not values:
        return "unknown"

    numeric_count = 0
    for v in values:
        try:
            float(v)
            numeric_count += 1
        except (ValueError, TypeError):
            pass

    if numeric_count == len(values):
        return "numeric"
    elif numeric_count > len(values) / 2:
        return "mixed"
    return "text"


def _compare(cell_value: str, operator: str, target: Any) -> bool:
    """Compare a cell value against a target using the given operator."""
    try:
        if operator == "contains":
            return str(target).lower() in cell_value.lower()
        elif operator == "eq":
            try:
                return float(cell_value) == float(target)
            except (ValueError, TypeError):
                return cell_value == str(target)
        elif operator == "ne":
            try:
                return float(cell_value) != float(target)
            except (ValueError, TypeError):
                return cell_value != str(target)
        elif operator in ("gt", "lt", "gte", "lte"):
            num_cell = float(cell_value)
            num_target = float(target)
            if operator == "gt":
                return num_cell > num_target
            elif operator == "lt":
                return num_cell < num_target
            elif operator == "gte":
                return num_cell >= num_target
            elif operator == "lte":
                return num_cell <= num_target
        return False
    except (ValueError, TypeError):
        return False


def json_read(path: str, encoding: str = "utf-8") -> dict:
    """
    Read a JSON file into a dictionary or list.

    Args:
        path: Path to the JSON file.
        encoding: File encoding.

    Returns:
        Dict with 'success' and 'data'.
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {"success": False, "error": f"File not found: {path}"}

    try:
        with open(path, "r", encoding=encoding) as f:
            data = json.load(f)
        return {"success": True, "path": path, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


def json_write(path: str, data: Any, indent: int = 4, encoding: str = "utf-8") -> dict:
    """
    Write a dictionary or list to a JSON file.

    Args:
        path: Path to save the JSON file.
        data: Data to write (must be JSON serializable).
        indent: Indentation level for pretty-printing.
        encoding: File encoding.

    Returns:
        Dict with 'success' and file info.
    """
    path = os.path.abspath(path)
    try:
        with open(path, "w", encoding=encoding) as f:
            json.dump(data, f, indent=indent)
        return {"success": True, "path": path, "message": "Successfully wrote JSON data."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def merge_csv(path1: str, path2: str, output_path: str, join_column: str, how: str = "inner", encoding: str = "utf-8") -> dict:
    """
    Merge two CSV files based on a common column without pandas.

    Args:
        path1: Path to the first CSV file.
        path2: Path to the second CSV file.
        output_path: Path to save the merged CSV.
        join_column: The common column to merge on.
        how: 'inner', 'left', 'right', or 'outer'.
        encoding: File encoding.

    Returns:
        Dict with 'success', 'path', and 'row_count'.
    """
    path1 = os.path.abspath(path1)
    path2 = os.path.abspath(path2)
    output_path = os.path.abspath(output_path)

    if not os.path.exists(path1):
        return {"success": False, "error": f"File not found: {path1}"}
    if not os.path.exists(path2):
        return {"success": False, "error": f"File not found: {path2}"}

    try:
        with open(path1, "r", encoding=encoding, newline="") as f1:
            reader1 = list(csv.DictReader(f1))
        with open(path2, "r", encoding=encoding, newline="") as f2:
            reader2 = list(csv.DictReader(f2))

        if not reader1 or not reader2:
            return {"success": False, "error": "One or both CSV files are empty."}

        fields1 = list(reader1[0].keys())
        fields2 = list(reader2[0].keys())
        
        if join_column not in fields1 or join_column not in fields2:
            return {"success": False, "error": f"Join column '{join_column}' not found in both files."}

        map1 = {str(row[join_column]): row for row in reader1}
        map2 = {str(row[join_column]): row for row in reader2}

        all_keys = set()
        if how in ("inner", "left", "outer"):
            all_keys.update(map1.keys())
        if how in ("right", "outer"):
            all_keys.update(map2.keys())

        if how == "inner":
            keys = [k for k in all_keys if k in map1 and k in map2]
        elif how == "left":
            keys = [k for k in all_keys if k in map1]
        elif how == "right":
            keys = [k for k in all_keys if k in map2]
        elif how == "outer":
            keys = list(all_keys)
        else:
            return {"success": False, "error": f"Invalid merge type: {how}"}

        output_fields = fields1.copy()
        for f in fields2:
            if f not in output_fields:
                output_fields.append(f)

        merged_rows = []
        for k in keys:
            row1 = map1.get(k, {f: "" for f in fields1})
            row2 = map2.get(k, {f: "" for f in fields2})
            merged_row = {}
            for f in output_fields:
                if f in row1 and row1[f] != "":
                    merged_row[f] = row1[f]
                elif f in row2:
                    merged_row[f] = row2[f]
                else:
                    merged_row[f] = ""
            merged_rows.append(merged_row)

        with open(output_path, "w", encoding=encoding, newline="") as fout:
            writer = csv.DictWriter(fout, fieldnames=output_fields)
            writer.writeheader()
            writer.writerows(merged_rows)

        return {"success": True, "path": output_path, "row_count": len(merged_rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}
