"""
Built-in Network Tools.

Deterministic Python functions for basic network diagnostics.
"""

import socket
import subprocess
import platform
from typing import Optional

def ping_host(host: Optional[str] = None, task: Optional[str] = None) -> dict:
    """
    Ping a host to check network connectivity.

    Args:
        host: Hostname or IP address to ping.
        task: Natural language task to extract host from if missing.

    Returns:
        Dict with ping results.
    """
    target = host or task
    if not target:
        return {"success": False, "error": "No host provided to ping."}
        
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command = ['ping', param, '1', target]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Ping to {target} timed out."}
    except Exception as e:
        return {"success": False, "error": f"Failed to execute ping: {str(e)}"}

def check_port_open(host: Optional[str] = None, port: Optional[int] = None, task: Optional[str] = None) -> dict:
    """
    Check if a specific port is open on a host.

    Args:
        host: Hostname or IP address.
        port: Port number.
        task: Natural language task containing host and port if missing.

    Returns:
        Dict with port status.
    """
    target_host = host
    target_port = port
    
    # Very naive fallback parsing if task is provided but args aren't.
    if not target_host or not target_port:
        if task:
            parts = task.split()
            # Simple heuristic: look for numbers
            for p in parts:
                if p.isdigit():
                    target_port = int(p)
                elif '.' in p or 'localhost' in p:
                    target_host = p
                    
    if not target_host or not target_port:
        return {"success": False, "error": "Both host and port must be provided."}
        
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3.0)
            result = s.connect_ex((target_host, int(target_port)))
            
        is_open = (result == 0)
        return {
            "success": True,
            "is_open": is_open,
            "message": f"Port {target_port} on {target_host} is {'open' if is_open else 'closed'}"
        }
    except socket.gaierror:
        return {"success": False, "error": f"Hostname {target_host} could not be resolved."}
    except socket.error as e:
        return {"success": False, "error": f"Socket error: {str(e)}"}


def download_file(url: str, output_path: str, timeout: int = 30) -> dict:
    """
    Download a file from a URL to a local path.
    
    Args:
        url: The URL to download from.
        output_path: The local file path to save the file.
        timeout: Network timeout in seconds.
        
    Returns:
        Dict with 'success' and file information.
    """
    import urllib.request
    import urllib.error
    import os
    
    output_path = os.path.abspath(output_path)
    
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            with open(output_path, "wb") as f:
                f.write(response.read())
                
        return {
            "success": True, 
            "message": f"Successfully downloaded file to {output_path}",
            "path": output_path,
            "size_bytes": os.path.getsize(output_path)
        }
    except urllib.error.URLError as e:
        return {"success": False, "error": f"Failed to download: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": f"Error: {str(e)}"}
