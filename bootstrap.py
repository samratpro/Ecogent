#!/usr/bin/env python3
"""
Ecogent Bootstrap Script

Idempotent environment setup for the Ecogent experiment.
Downloads runtime, model, installs dependencies, and verifies everything.

Usage:
    python bootstrap.py
"""

import hashlib
import io
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

# ============================================================
# Constants
# ============================================================

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

DIRECTORIES = [
    "runtime",
    "models/tiny",
    "data/chroma",
    "tools/builtin",
    "tools/generated",
    "projects",
    "workflows",
    "results",
    "logs",
    "config",
    "cache",
    "benchmark",
    "tests",
]

MANIFEST_PATH = os.path.join(ROOT_DIR, "config", "runtime_manifest.json")
CONFIG_PATH = os.path.join(ROOT_DIR, "config", "config.json")
MODEL_META_PATH = os.path.join(ROOT_DIR, "config", "model.json")
VENV_DIR = os.path.join(ROOT_DIR, ".venv")
REQUIREMENTS_PATH = os.path.join(ROOT_DIR, "requirements.txt")


# ============================================================
# Helpers
# ============================================================


def print_header(title: str) -> None:
    """Print a formatted section header."""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)
    print()


def print_status(ok: bool, message: str) -> None:
    """Print a status line with check/cross mark."""
    mark = "✓" if ok else "✗"
    print(f"  {mark} {message}")


def get_platform_key() -> str:
    """Detect platform and return the manifest key."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        if machine in ("x86_64", "amd64"):
            return "windows-x64"
    elif system == "linux":
        if machine in ("x86_64", "amd64"):
            return "linux-x64"
    elif system == "darwin":
        if machine == "arm64":
            return "macos-arm64"
        elif machine in ("x86_64", "amd64"):
            return "macos-x64"

    return f"{system}-{machine}"


def get_ram_gb() -> float:
    """Get total RAM in GB."""
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        pass

    # Fallback: platform-specific
    system = platform.system().lower()
    if system == "windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            c_ulong = ctypes.c_ulonglong
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", c_ulong),
                    ("ullAvailPhys", c_ulong),
                    ("ullTotalPageFile", c_ulong),
                    ("ullAvailPageFile", c_ulong),
                    ("ullTotalVirtual", c_ulong),
                    ("ullAvailVirtual", c_ulong),
                    ("ullAvailExtendedVirtual", c_ulong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        except Exception:
            pass
    elif system == "linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        return kb / (1024 ** 2)
        except Exception:
            pass
    elif system == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True
            )
            return int(result.stdout.strip()) / (1024 ** 3)
        except Exception:
            pass

    return 0.0


def get_gpu_info() -> str:
    """Attempt to detect GPU."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "None detected"


def sha256_file(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: str, desc: str = "") -> bool:
    """Download a file with progress indication. Uses atomic rename."""
    tmp_dest = dest + ".download"
    try:
        print(f"  Downloading: {desc or url}")
        print(f"  → {dest}")

        req = urllib.request.Request(url, headers={"User-Agent": "Ecogent-Bootstrap/0.1"})
        with urllib.request.urlopen(req, timeout=300) as response:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0

            with open(tmp_dest, "wb") as f:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 // total
                        mb = downloaded / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        print(
                            f"\r  Progress: {mb:.1f}/{total_mb:.1f} MB ({pct}%)",
                            end="", flush=True,
                        )

        print()  # newline after progress

        # Atomic rename
        if os.path.exists(dest):
            os.remove(dest)
        os.rename(tmp_dest, dest)
        return True

    except Exception as e:
        print(f"\n  ✗ Download failed: {e}")
        # Preserve partial file for resume
        if os.path.exists(tmp_dest):
            print(f"  Partial download preserved: {tmp_dest}")
        return False


def extract_archive(archive_path: str, dest_dir: str, archive_type: str) -> bool:
    """Extract a zip or tar.gz archive."""
    try:
        if archive_type == "zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(dest_dir)
        elif archive_type in ("tar.gz", "tgz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(dest_dir)
        else:
            print(f"  ✗ Unknown archive type: {archive_type}")
            return False
        return True
    except Exception as e:
        print(f"  ✗ Extraction failed: {e}")
        return False


# ============================================================
# Step 1: Check Python
# ============================================================

def check_python() -> bool:
    """Verify Python version >= 3.10."""
    ver = sys.version_info
    ok = ver >= (3, 10)
    print_status(ok, f"Python {ver.major}.{ver.minor}.{ver.micro}")
    if not ok:
        print("    Python 3.10+ is required.")
    return ok


# ============================================================
# Step 2-5: System Detection
# ============================================================

def detect_system() -> dict:
    """Detect and display system information."""
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_arch": platform.machine(),
        "cpu_cores": os.cpu_count() or 0,
        "ram_gb": round(get_ram_gb(), 1),
        "gpu": get_gpu_info(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform_key": get_platform_key(),
    }

    print_status(True, f"OS: {info['os']} {info['os_version']}")
    print_status(True, f"CPU: {info['cpu']}")
    print_status(True, f"CPU Cores: {info['cpu_cores']}")
    print_status(True, f"RAM: {info['ram_gb']} GB")
    print_status(True, f"GPU: {info['gpu']}")
    print_status(True, f"Platform: {info['platform_key']}")

    return info


# ============================================================
# Step 6: Virtual Environment
# ============================================================

def setup_venv() -> bool:
    """Create virtual environment if it doesn't exist."""
    if os.path.exists(VENV_DIR):
        print_status(True, "Virtual environment exists")
        return True

    print("  Creating virtual environment...")
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", VENV_DIR],
            check=True, capture_output=True, text=True,
        )
        print_status(True, "Virtual environment created")
        return True
    except subprocess.CalledProcessError as e:
        print_status(False, f"Failed to create venv: {e.stderr}")
        return False


def get_venv_python() -> str:
    """Get the path to the venv Python executable."""
    if platform.system() == "Windows":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def get_venv_pip() -> str:
    """Get the path to the venv pip executable."""
    if platform.system() == "Windows":
        return os.path.join(VENV_DIR, "Scripts", "pip.exe")
    return os.path.join(VENV_DIR, "bin", "pip")


# ============================================================
# Step 7: Install Dependencies
# ============================================================

def install_dependencies() -> bool:
    """Install Python dependencies into venv."""
    pip = get_venv_pip()
    python = get_venv_python()

    if not os.path.exists(pip):
        # Use python -m pip as fallback
        pip_cmd = [python, "-m", "pip"]
    else:
        pip_cmd = [pip]

    # Upgrade pip first
    print("  Upgrading pip...")
    try:
        subprocess.run(
            [python, "-m", "pip", "install", "--upgrade", "pip"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        print("  Warning: pip upgrade failed, continuing...")

    # Install requirements
    print("  Installing dependencies from requirements.txt...")
    try:
        subprocess.run(
            pip_cmd + ["install", "-r", REQUIREMENTS_PATH],
            check=True, capture_output=True, text=True,
        )
        print_status(True, "Dependencies installed")
        return True
    except subprocess.CalledProcessError as e:
        print_status(False, f"Dependency installation failed")
        print(f"    {e.stderr[:500]}")
        return False


def install_project() -> bool:
    """Install the ecogent_experiment package in development mode."""
    python = get_venv_python()
    print("  Installing ecogent_experiment package...")
    try:
        subprocess.run(
            [python, "-m", "pip", "install", "-e", ROOT_DIR],
            check=True, capture_output=True, text=True,
        )
        print_status(True, "ecogent_experiment package installed")
        return True
    except subprocess.CalledProcessError as e:
        print_status(False, f"Package installation failed")
        print(f"    {e.stderr[:500]}")
        return False


# ============================================================
# Step 8: Prepare Runtime
# ============================================================

def setup_runtime(platform_key: str) -> bool:
    """Download and install llama.cpp runtime."""
    # Load manifest
    if not os.path.exists(MANIFEST_PATH):
        print_status(False, "Runtime manifest not found")
        return False

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    if platform_key not in manifest:
        print_status(False, f"Unsupported platform: {platform_key}")
        print(f"    Supported: {', '.join(k for k in manifest if k != 'model' and not k.startswith('_'))}")
        return False

    entry = manifest[platform_key]
    runtime_dir = os.path.join(ROOT_DIR, "runtime")
    binary_name = entry["binary_name"]
    binary_path = os.path.join(runtime_dir, binary_name)

    # Check if binary already exists
    if os.path.exists(binary_path):
        print_status(True, f"Runtime binary exists: {binary_name}")
        return True

    # Download
    archive_ext = "zip" if entry["archive_type"] == "zip" else "tar.gz"
    archive_name = f"llama-runtime.{archive_ext}"
    archive_path = os.path.join(ROOT_DIR, "cache", archive_name)

    if not download_file(entry["url"], archive_path, f"llama.cpp ({platform_key})"):
        return False

    # Extract to temp dir then move binary
    tmp_extract = os.path.join(ROOT_DIR, "cache", "runtime_extract")
    if os.path.exists(tmp_extract):
        shutil.rmtree(tmp_extract)
    os.makedirs(tmp_extract)

    if not extract_archive(archive_path, tmp_extract, entry["archive_type"]):
        return False

    # Find the binary in extracted files
    found_binary = None
    for dirpath, dirnames, filenames in os.walk(tmp_extract):
        for fname in filenames:
            if fname == binary_name:
                found_binary = os.path.join(dirpath, fname)
                break
        if found_binary:
            break

    if not found_binary:
        # On some archives, binaries are in a build/bin subdir
        # Try to find any llama-cli executable
        for dirpath, dirnames, filenames in os.walk(tmp_extract):
            for fname in filenames:
                if "llama-cli" in fname:
                    found_binary = os.path.join(dirpath, fname)
                    break
            if found_binary:
                break

    if not found_binary:
        print_status(False, f"Binary '{binary_name}' not found in archive")
        # List what we got
        for dirpath, dirnames, filenames in os.walk(tmp_extract):
            for fname in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fname), tmp_extract)
                print(f"    Found: {rel}")
        return False

    # Copy binary and all DLLs/shared libs to runtime dir
    extract_source_dir = os.path.dirname(found_binary)
    for fname in os.listdir(extract_source_dir):
        src = os.path.join(extract_source_dir, fname)
        dst = os.path.join(runtime_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    # Make executable on Unix
    if platform.system() != "Windows":
        os.chmod(binary_path, 0o755)

    # Cleanup
    shutil.rmtree(tmp_extract, ignore_errors=True)

    if os.path.exists(binary_path):
        print_status(True, f"Runtime installed: {binary_name}")
        return True
    else:
        print_status(False, "Runtime installation failed")
        return False


# ============================================================
# Step 9-10: Download and Verify Model
# ============================================================

def setup_model() -> bool:
    """Download and verify the Tiny LLM model."""
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    model_info = manifest["model"]
    model_dir = os.path.join(ROOT_DIR, "models", "tiny")
    model_path = os.path.join(model_dir, model_info["filename"])

    # Check if model already exists
    if os.path.exists(model_path):
        size_mb = os.path.getsize(model_path) / (1024 * 1024)
        print_status(True, f"Model exists: {model_info['filename']} ({size_mb:.1f} MB)")

        # Verify checksum if we have one stored
        if model_info.get("sha256"):
            actual_hash = sha256_file(model_path)
            if actual_hash == model_info["sha256"]:
                print_status(True, "Model checksum verified")
            else:
                print_status(False, "Model checksum mismatch! Re-downloading...")
                os.remove(model_path)
                # Fall through to download
            if os.path.exists(model_path):
                _save_model_metadata(model_path, model_info)
                return True

        _save_model_metadata(model_path, model_info)
        return True

    # Download
    if not download_file(model_info["url"], model_path, model_info["name"]):
        return False

    size_mb = os.path.getsize(model_path) / (1024 * 1024)
    print_status(True, f"Model downloaded: {size_mb:.1f} MB")

    # Compute and store checksum
    actual_hash = sha256_file(model_path)
    if model_info.get("sha256") and actual_hash != model_info["sha256"]:
        print_status(False, f"Checksum mismatch!")
        print(f"    Expected: {model_info['sha256']}")
        print(f"    Got:      {actual_hash}")
        return False

    # Store hash if not in manifest
    if not model_info.get("sha256"):
        model_info["sha256"] = actual_hash
        manifest["model"] = model_info
        with open(MANIFEST_PATH, "w") as f:
            json.dump(manifest, f, indent=2)
        print_status(True, f"Model checksum recorded: {actual_hash[:16]}...")

    _save_model_metadata(model_path, model_info)
    return True


def _save_model_metadata(model_path: str, model_info: dict) -> None:
    """Save model metadata to config/model.json."""
    meta = {
        "name": model_info["name"],
        "format": model_info["format"],
        "quantization": model_info["quantization"],
        "parameters": model_info["parameters"],
        "path": os.path.relpath(model_path, ROOT_DIR),
        "sha256": model_info.get("sha256", ""),
        "file_size_bytes": os.path.getsize(model_path),
    }
    with open(MODEL_META_PATH, "w") as f:
        json.dump(meta, f, indent=2)


# ============================================================
# Step 11: Initialize Chroma
# ============================================================

def setup_chroma() -> bool:
    """Initialize ChromaDB."""
    chroma_dir = os.path.join(ROOT_DIR, "data", "chroma")

    try:
        # Import from venv
        python = get_venv_python()
        result = subprocess.run(
            [python, "-c", """
import chromadb
import json
import os

chroma_dir = os.path.join(os.environ.get('ECOGENT_ROOT', '.'), 'data', 'chroma')
client = chromadb.PersistentClient(path=chroma_dir)

# Create collections if they don't exist
collections = ['builtin_tools', 'generated_tools', 'project_tools', 'workflow_memory', 'browser_patterns']
for name in collections:
    client.get_or_create_collection(
        name=name,
        metadata={"description": f"Ecogent {name} collection"}
    )

existing = [c.name for c in client.list_collections()]
print(json.dumps(existing))
"""],
            capture_output=True, text=True,
            env={**os.environ, "ECOGENT_ROOT": ROOT_DIR},
        )

        if result.returncode == 0:
            collections = json.loads(result.stdout.strip())
            print_status(True, f"Chroma initialized ({len(collections)} collections)")
            return True
        else:
            print_status(False, f"Chroma initialization failed")
            if result.stderr:
                print(f"    {result.stderr[:300]}")
            return False

    except Exception as e:
        print_status(False, f"Chroma setup error: {e}")
        return False


# ============================================================
# Step 12: Create Directories
# ============================================================

def create_directories() -> bool:
    """Create all required project directories."""
    created = 0
    for d in DIRECTORIES:
        path = os.path.join(ROOT_DIR, d)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            created += 1

    # Create __init__.py files for Python packages
    init_dirs = [
        "ecogent_experiment",
        "ecogent_experiment/agents",
        "ecogent_experiment/providers",
        "tools",
        "tools/builtin",
        "tools/generated",
        "tests",
    ]
    for d in init_dirs:
        init_path = os.path.join(ROOT_DIR, d, "__init__.py")
        if not os.path.exists(init_path):
            os.makedirs(os.path.join(ROOT_DIR, d), exist_ok=True)
            with open(init_path, "w") as f:
                f.write("")

    print_status(True, f"Directories ready ({created} created)")
    return True


# ============================================================
# Step 13: Register Built-in Tools
# ============================================================

def register_builtin_tools() -> bool:
    """Register built-in tools in Chroma."""
    python = get_venv_python()

    # Define built-in tools metadata
    tools = [
        {"tool_key": "read_file", "natural_name": "Read File", "description": "Read the contents of a local file", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "write_file", "natural_name": "Write File", "description": "Write content to a local file", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "rename_file", "natural_name": "Rename File", "description": "Rename a local file from one path to another", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "copy_file", "natural_name": "Copy File", "description": "Copy a file to a new location", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "move_file", "natural_name": "Move File", "description": "Move a file to a different directory", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "delete_file", "natural_name": "Delete File", "description": "Delete a local file permanently", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "list_directory", "natural_name": "List Directory", "description": "List all files and subdirectories in a directory", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "create_directory", "natural_name": "Create Directory", "description": "Create a new directory or folder", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "search_files", "natural_name": "Search Files", "description": "Search for files matching a pattern or name", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "file_exists", "natural_name": "File Exists", "description": "Check whether a file or directory exists", "category": "filesystem", "agent": "os_agent"},
        {"tool_key": "read_csv", "natural_name": "Read CSV", "description": "Read a CSV file into a data structure", "category": "data", "agent": "os_agent"},
        {"tool_key": "inspect_csv", "natural_name": "Inspect CSV", "description": "Inspect the structure, columns and row count of a CSV file", "category": "data", "agent": "os_agent"},
        {"tool_key": "calculate_statistics", "natural_name": "Calculate Statistics", "description": "Calculate statistical measures like mean, median, std for numerical data", "category": "data", "agent": "os_agent"},
        {"tool_key": "filter_dataframe", "natural_name": "Filter Dataframe", "description": "Filter rows from a CSV or dataframe based on conditions", "category": "data", "agent": "os_agent"},
        {"tool_key": "save_csv", "natural_name": "Save CSV", "description": "Save data to a CSV file", "category": "data", "agent": "os_agent"},
        {"tool_key": "system_info", "natural_name": "System Info", "description": "Get system information including OS, CPU, RAM and disk usage", "category": "system", "agent": "os_agent"},
        {"tool_key": "process_info", "natural_name": "Process Info", "description": "Get information about running processes", "category": "system", "agent": "os_agent"},
        {"tool_key": "run_python_test", "natural_name": "Run Python Test", "description": "Run Python unit tests using pytest", "category": "testing", "agent": "testing_agent"},
        {"tool_key": "verify_file", "natural_name": "Verify File", "description": "Verify that a file exists and optionally check its content", "category": "testing", "agent": "testing_agent"},
        {"tool_key": "verify_directory", "natural_name": "Verify Directory", "description": "Verify that a directory exists and optionally check its contents", "category": "testing", "agent": "testing_agent"},
        {"tool_key": "run_flaml_automl", "natural_name": "Run FLAML AutoML", "description": "Run FLAML AutoML to train a machine learning model on a CSV dataset", "category": "data", "agent": "os_agent"},
        {"tool_key": "web_search", "natural_name": "Web Search", "description": "Search the internet/google for information or current time", "category": "web", "agent": "browser_agent"},
        {"tool_key": "browse_website", "natural_name": "Browse Website", "description": "Navigate to a URL and read its contents", "category": "web", "agent": "browser_agent"},
        {"tool_key": "browser_task", "natural_name": "Browser Task", "description": "Execute a multi-step browser automation task using Playwright. Automatically records workflow on first run and replays on subsequent runs.", "category": "web", "agent": "browser_agent"},
    ]

    try:
        result = subprocess.run(
            [python, "-c", f"""
import chromadb
import json
import os

chroma_dir = os.path.join(os.environ.get('ECOGENT_ROOT', '.'), 'data', 'chroma')
client = chromadb.PersistentClient(path=chroma_dir)
collection = client.get_or_create_collection(name='builtin_tools')

tools = {json.dumps(tools)}

# Check what's already registered
existing = set()
try:
    existing_data = collection.get()
    if existing_data and existing_data.get('ids'):
        existing = set(existing_data['ids'])
except Exception:
    pass

added = 0
for tool in tools:
    if tool['tool_key'] not in existing:
        collection.add(
            ids=[tool['tool_key']],
            documents=[tool['description']],
            metadatas=[{{
                'natural_name': tool['natural_name'],
                'category': tool['category'],
                'agent': tool['agent'],
                'execution': 'local',
                'persistent': True
            }}]
        )
        added += 1

print(json.dumps({{'total': len(tools), 'added': added, 'existing': len(existing)}}))
"""],
            capture_output=True, text=True,
            env={**os.environ, "ECOGENT_ROOT": ROOT_DIR},
        )

        if result.returncode == 0:
            stats = json.loads(result.stdout.strip())
            print_status(True, f"Built-in tools registered ({stats['total']} total, {stats['added']} new)")
            return True
        else:
            print_status(False, "Tool registration failed")
            if result.stderr:
                print(f"    {result.stderr[:300]}")
            return False

    except Exception as e:
        print_status(False, f"Tool registration error: {e}")
        return False


# ============================================================
# Step 15: Health Checks
# ============================================================

def health_check_inference(platform_key: str) -> bool:
    """Test local Tiny LLM inference."""
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    model_info = manifest["model"]
    model_path = os.path.join(ROOT_DIR, "models", "tiny", model_info["filename"])

    if platform_key not in manifest:
        print_status(False, "Cannot test inference: unsupported platform")
        return False

    entry = manifest[platform_key]
    binary_name = entry["binary_name"]
    binary_path = os.path.join(ROOT_DIR, "runtime", binary_name)

    if not os.path.exists(binary_path):
        print_status(False, "Cannot test inference: runtime not found")
        return False

    if not os.path.exists(model_path):
        print_status(False, "Cannot test inference: model not found")
        return False

    # Run a simple classification test
    test_prompt = (
        "<|im_start|>system\n"
        "You are a task classifier. Respond with JSON only.\n"
        "<|im_end|>\n"
        "<|im_start|>user\n"
        'Classify this task: "List all files in the current directory"\n'
        "Respond with: {\"intent\": \"...\", \"complexity\": \"simple|complex\"}\n"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    try:
        result = subprocess.run(
            [
                binary_path,
                "-m", model_path,
                "-p", test_prompt,
                "-n", "64",
                "--temp", "0.1",
                "--ctx-size", "256",
                "--no-display-prompt",
                "--log-disable",
            ],
            capture_output=True, text=True, timeout=120,
        )

        if result.returncode == 0 and len(result.stdout.strip()) > 0:
            output = result.stdout.strip()[:200]
            print_status(True, f"Local inference successful")
            print(f"    Output preview: {output[:100]}...")
            return True
        else:
            print_status(False, "Local inference returned empty or failed")
            if result.stderr:
                # Filter out model loading info
                err_lines = [l for l in result.stderr.split('\n') if 'error' in l.lower() or 'fail' in l.lower()]
                if err_lines:
                    print(f"    {err_lines[0][:200]}")
            return False

    except subprocess.TimeoutExpired:
        print_status(False, "Local inference timed out (>120s)")
        return False
    except Exception as e:
        print_status(False, f"Inference test error: {e}")
        return False


def health_check_chroma() -> bool:
    """Test Chroma query."""
    python = get_venv_python()
    try:
        result = subprocess.run(
            [python, "-c", f"""
import chromadb
import os

chroma_dir = os.path.join(os.environ.get('ECOGENT_ROOT', '.'), 'data', 'chroma')
client = chromadb.PersistentClient(path=chroma_dir)
collection = client.get_collection('builtin_tools')

# Test semantic query
results = collection.query(
    query_texts=["change the name of this file"],
    n_results=3
)

if results and results['ids'] and len(results['ids'][0]) > 0:
    top = results['ids'][0][0]
    print(f"OK:{{top}}")
else:
    print("FAIL:no results")
"""],
            capture_output=True, text=True,
            env={**os.environ, "ECOGENT_ROOT": ROOT_DIR},
        )

        if result.returncode == 0 and result.stdout.startswith("OK:"):
            top_tool = result.stdout.strip().split(":")[1]
            print_status(True, f"Chroma query works (\"change file name\" → {top_tool})")
            return True
        else:
            print_status(False, "Chroma query test failed")
            return False

    except Exception as e:
        print_status(False, f"Chroma health check error: {e}")
        return False


def health_check_tools() -> bool:
    """Test a basic tool operation."""
    # Simple test: create and read a temp file
    test_dir = os.path.join(ROOT_DIR, "cache")
    test_file = os.path.join(test_dir, "_bootstrap_test.txt")
    try:
        with open(test_file, "w") as f:
            f.write("Ecogent bootstrap test")
        with open(test_file, "r") as f:
            content = f.read()
        os.remove(test_file)

        if content == "Ecogent bootstrap test":
            print_status(True, "Tool execution test passed")
            return True
        else:
            print_status(False, "Tool execution test: content mismatch")
            return False
    except Exception as e:
        print_status(False, f"Tool execution test failed: {e}")
        return False


def health_check_json_parser() -> bool:
    """Test JSON extraction from model-like output."""
    python = get_venv_python()
    try:
        result = subprocess.run(
            [python, "-c", """
import json
import re

# Simulate model output with surrounding text
model_output = '''Here is the classification:
```json
{"intent": "file_operation", "complexity": "simple", "tool": "rename_file"}
```
That is my response.'''

# Extract JSON
pattern = r'\\{[^{}]*\\}'
matches = re.findall(pattern, model_output)
if matches:
    parsed = json.loads(matches[0])
    if parsed.get('intent') == 'file_operation':
        print("OK")
    else:
        print("FAIL:wrong content")
else:
    print("FAIL:no match")
"""],
            capture_output=True, text=True,
        )

        if result.returncode == 0 and "OK" in result.stdout:
            print_status(True, "JSON parser test passed")
            return True
        else:
            print_status(False, "JSON parser test failed")
            return False

    except Exception as e:
        print_status(False, f"JSON parser test error: {e}")
        return False


# ============================================================
# Step 18: Final Report
# ============================================================

def print_final_report(results: dict) -> None:
    """Print the final environment report."""
    all_ok = all(results.values())

    print()
    print("=" * 60)
    if all_ok:
        print("         ECOGENT ENVIRONMENT READY")
    else:
        print("     ECOGENT ENVIRONMENT SETUP (PARTIAL)")
    print("=" * 60)
    print()

    for key, ok in results.items():
        print_status(ok, key)

    print()
    if all_ok:
        venv_activate = (
            ".venv\\Scripts\\activate"
            if platform.system() == "Windows"
            else "source .venv/bin/activate"
        )
        print("  Run:")
        print()
        print(f"    {venv_activate}")
        print("    ecogent system-info")
        print()
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"  {len(failed)} component(s) need attention.")
        print("  Re-run: python bootstrap.py")
        print()

    print("=" * 60)


# ============================================================
# Main
# ============================================================

def main() -> int:
    """Run the complete bootstrap process."""
    print()
    print("=" * 60)
    print("           ECOGENT ENVIRONMENT SETUP")
    print("=" * 60)

    results = {}

    # 1. Check Python
    print_header("System")
    if not check_python():
        return 1

    # 2-5. Detect system
    sys_info = detect_system()
    results["System detection"] = True

    # 12. Create directories (early, needed by other steps)
    print_header("Directories")
    results["Directories"] = create_directories()

    # 6. Virtual environment
    print_header("Python Environment")
    results["Virtual environment"] = setup_venv()
    if not results["Virtual environment"]:
        print("  Cannot continue without virtual environment.")
        print_final_report(results)
        return 1

    # 7. Dependencies
    results["Dependencies"] = install_dependencies()
    if not results["Dependencies"]:
        print("  Cannot continue without dependencies.")
        print_final_report(results)
        return 1

    # Install project package
    results["Package install"] = install_project()

    # 8. Runtime
    print_header("Local LLM Runtime")
    results["Runtime (llama.cpp)"] = setup_runtime(sys_info["platform_key"])

    # 9-10. Model
    print_header("Tiny LLM Model")
    results["Model (SmolLM2-135M)"] = setup_model()

    # 11. Chroma
    print_header("Semantic Memory")
    results["Chroma initialized"] = setup_chroma()

    # 13. Register tools
    if results["Chroma initialized"]:
        results["Built-in tools registered"] = register_builtin_tools()
    else:
        results["Built-in tools registered"] = False

    # 15-17. Health checks
    print_header("Health Checks")
    if results["Runtime (llama.cpp)"] and results["Model (SmolLM2-135M)"]:
        results["Inference test"] = health_check_inference(sys_info["platform_key"])
    else:
        results["Inference test"] = False
        print_status(False, "Skipped inference test (runtime or model missing)")

    if results["Built-in tools registered"]:
        results["Chroma query test"] = health_check_chroma()
    else:
        results["Chroma query test"] = False
        print_status(False, "Skipped Chroma test (tools not registered)")

    results["Tool execution test"] = health_check_tools()
    results["JSON parser test"] = health_check_json_parser()

    # 18. Report
    print_final_report(results)

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
