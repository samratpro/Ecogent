"""
Built-in System Tools.

Deterministic Python functions for system information retrieval.
"""

import os
import platform
import sys
from typing import Optional

import psutil


def system_info() -> dict:
    """
    Get system information including OS, CPU, RAM and disk usage.

    Returns:
        Dict with system details.
    """
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(os.getcwd())

    return {
        "success": True,
        "os": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_arch": platform.machine(),
        "cpu_cores_physical": psutil.cpu_count(logical=False),
        "cpu_cores_logical": psutil.cpu_count(logical=True),
        "ram_total_gb": round(mem.total / (1024 ** 3), 2),
        "ram_available_gb": round(mem.available / (1024 ** 3), 2),
        "ram_used_percent": mem.percent,
        "disk_total_gb": round(disk.total / (1024 ** 3), 2),
        "disk_free_gb": round(disk.free / (1024 ** 3), 2),
        "disk_used_percent": disk.percent,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "hostname": platform.node(),
    }


def process_info(name: Optional[str] = None, top_n: int = 10) -> dict:
    """
    Get information about running processes.

    Args:
        name: Optional process name to filter by.
        top_n: Number of top processes to return (by memory usage).

    Returns:
        Dict with 'success', 'processes' list, 'total_count'.
    """
    try:
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
            try:
                info = proc.info
                if name and name.lower() not in info["name"].lower():
                    continue
                processes.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "cpu_percent": info.get("cpu_percent", 0),
                    "memory_mb": round(
                        info["memory_info"].rss / (1024 * 1024), 1
                    ) if info.get("memory_info") else 0,
                    "status": info.get("status", "unknown"),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by memory usage, take top N
        processes.sort(key=lambda p: p["memory_mb"], reverse=True)
        top = processes[:top_n]

        return {
            "success": True,
            "processes": top,
            "total_count": len(processes),
            "showing": len(top),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
