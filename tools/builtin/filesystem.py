"""
Built-in Filesystem Tools.

Deterministic Python functions for filesystem operations.
These tools are permanent and cannot be deleted by the agent.
"""

import csv
import fnmatch
import os
import shutil
from typing import Any, Optional


def read_file(path: str, encoding: str = "utf-8") -> dict:
    """
    Read the contents of a local file.

    Args:
        path: Path to the file to read.
        encoding: File encoding (default: utf-8).

    Returns:
        Dict with 'content', 'size_bytes', 'path'.
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {"success": False, "error": f"File not found: {path}"}
    if not os.path.isfile(path):
        return {"success": False, "error": f"Not a file: {path}"}

    try:
        with open(path, "r", encoding=encoding) as f:
            content = f.read()
        return {
            "success": True,
            "content": content,
            "size_bytes": os.path.getsize(path),
            "path": path,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(path: str, content: str, encoding: str = "utf-8") -> dict:
    """
    Write content to a local file.

    Args:
        path: Path to the file to write.
        content: Content to write.
        encoding: File encoding (default: utf-8).

    Returns:
        Dict with 'success', 'path', 'size_bytes'.
    """
    path = os.path.abspath(path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding=encoding) as f:
            f.write(content)
        return {
            "success": True,
            "path": path,
            "size_bytes": os.path.getsize(path),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def rename_file(source: str, destination: str) -> dict:
    """
    Rename a local file from one path to another.

    Args:
        source: Current file path.
        destination: New file path.

    Returns:
        Dict with 'success', 'source', 'destination'.
    """
    source = os.path.abspath(source)
    destination = os.path.abspath(destination)

    if not os.path.exists(source):
        return {"success": False, "error": f"Source not found: {source}"}
    if os.path.exists(destination):
        return {"success": False, "error": f"Destination already exists: {destination}"}

    try:
        os.rename(source, destination)
        return {"success": True, "source": source, "destination": destination}
    except Exception as e:
        return {"success": False, "error": str(e)}


def copy_file(source: str, destination: str) -> dict:
    """
    Copy a file to a new location.

    Args:
        source: Source file path.
        destination: Destination file path.

    Returns:
        Dict with 'success', 'source', 'destination'.
    """
    source = os.path.abspath(source)
    destination = os.path.abspath(destination)

    if not os.path.exists(source):
        return {"success": False, "error": f"Source not found: {source}"}

    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)
        return {"success": True, "source": source, "destination": destination}
    except Exception as e:
        return {"success": False, "error": str(e)}


def move_file(source: str, destination: str) -> dict:
    """
    Move a file to a different directory.

    Args:
        source: Source file path.
        destination: Destination file path.

    Returns:
        Dict with 'success', 'source', 'destination'.
    """
    source = os.path.abspath(source)
    destination = os.path.abspath(destination)

    if not os.path.exists(source):
        return {"success": False, "error": f"Source not found: {source}"}

    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.move(source, destination)
        return {"success": True, "source": source, "destination": destination}
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_file(path: str) -> dict:
    """
    Delete a local file permanently.

    Args:
        path: Path to the file to delete.

    Returns:
        Dict with 'success', 'path'.
    """
    path = os.path.abspath(path)

    if not os.path.exists(path):
        return {"success": False, "error": f"File not found: {path}"}

    try:
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        return {"success": True, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_directory(path: str = ".", pattern: str = "*") -> dict:
    """
    List all files and subdirectories in a directory.

    Args:
        path: Directory path to list.
        pattern: Glob pattern to filter results.

    Returns:
        Dict with 'success', 'path', 'entries' list.
    """
    path = os.path.abspath(path)

    if not os.path.exists(path):
        return {"success": False, "error": f"Directory not found: {path}"}
    if not os.path.isdir(path):
        return {"success": False, "error": f"Not a directory: {path}"}

    try:
        entries = []
        for name in sorted(os.listdir(path)):
            if not fnmatch.fnmatch(name, pattern):
                continue
            full_path = os.path.join(path, name)
            entry = {
                "name": name,
                "type": "directory" if os.path.isdir(full_path) else "file",
            }
            if os.path.isfile(full_path):
                entry["size_bytes"] = os.path.getsize(full_path)
            entries.append(entry)

        return {
            "success": True,
            "path": path,
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_directory(path: str) -> dict:
    """
    Create a new directory or folder.

    Args:
        path: Path for the new directory.

    Returns:
        Dict with 'success', 'path'.
    """
    path = os.path.abspath(path)

    try:
        os.makedirs(path, exist_ok=True)
        return {"success": True, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_files(directory: str = ".", pattern: str = "*", recursive: bool = True) -> dict:
    """
    Search for files matching a pattern or name.

    Args:
        directory: Directory to search in.
        pattern: Glob pattern to match.
        recursive: Whether to search subdirectories.

    Returns:
        Dict with 'success', 'matches' list.
    """
    directory = os.path.abspath(directory)

    if not os.path.exists(directory):
        return {"success": False, "error": f"Directory not found: {directory}"}

    try:
        matches = []
        if recursive:
            for dirpath, dirnames, filenames in os.walk(directory):
                for fname in filenames:
                    if fnmatch.fnmatch(fname, pattern):
                        matches.append(os.path.join(dirpath, fname))
        else:
            for fname in os.listdir(directory):
                if fnmatch.fnmatch(fname, pattern):
                    matches.append(os.path.join(directory, fname))

        return {
            "success": True,
            "directory": directory,
            "pattern": pattern,
            "matches": matches,
            "count": len(matches),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def file_exists(path: str) -> dict:
    """
    Check whether a file or directory exists.

    Args:
        path: Path to check.

    Returns:
        Dict with 'success', 'exists', 'type'.
    """
    path = os.path.abspath(path)
    exists = os.path.exists(path)

    result = {
        "success": True,
        "path": path,
        "exists": exists,
    }

    if exists:
        if os.path.isfile(path):
            result["type"] = "file"
            result["size_bytes"] = os.path.getsize(path)
        elif os.path.isdir(path):
            result["type"] = "directory"
        else:
            result["type"] = "other"

    return result
