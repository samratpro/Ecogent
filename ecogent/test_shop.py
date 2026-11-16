"""
The test shop (test_shop/, React + Node) as seen from the app: install / build / start / stop the server
on port 3010, read and change the site version through its key-protected lab API.
No GUI code here; the Benchmark window's "Test shop" tab uses it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
SHOP = REPO / "test_shop"
PORT = 3010
BASE = f"http://127.0.0.1:{PORT}"
PUBLIC_URL = f"http://localhost:{PORT}"
AXES = {"markup": ["baseline", "rebuild (hashed class names)", "refactor (wrappers, tags, DOM order)", "per-load class names"],
        "layout": ["baseline", "navigation and filters relocated", "redesign"],
        "copy": ["baseline", "rewritten labels"],
        "interruptions": ["none", "cookie banner", "cookie banner + newsletter modal"]}


def available() -> bool:
    return (SHOP / "server.js").exists() and (SHOP / "package.json").exists()


def node() -> Optional[str]:
    return shutil.which("node")


def npm_command() -> Optional[list[str]]:
    """npm as [node, npm-cli.js] when possible: version-manager shims (fnm, nvm) often fail outside their shell."""
    n = node()
    if n:
        cli = Path(n).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if cli.exists():
            return [n, str(cli)]
    exe = shutil.which("npm.cmd") or shutil.which("npm")
    return [exe] if exe else None


def needs_install() -> bool:
    return not (SHOP / "node_modules").exists()


def needs_build() -> bool:
    built = SHOP / "dist" / "index.html"
    if not built.exists():
        return True
    t = built.stat().st_mtime
    sources = [SHOP / "index.html", SHOP / "vite.config.js", *(SHOP / "src").rglob("*")]
    return any(p.is_file() and p.stat().st_mtime > t for p in sources)


def lab_key() -> str:
    try:
        return (SHOP / ".lab_key").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def lab(path: str, body: Optional[dict] = None, timeout: float = 3) -> dict:
    """Call the lab API; raises OSError / ValueError with a readable message."""
    req = urllib.request.Request(BASE + "/__lab" + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"x-lab-key": lab_key(), "content-type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ValueError(json.loads(e.read() or b"{}").get("error", f"HTTP {e.code}")) from None


def is_up() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/api/site", timeout=1.5) as r:
            return r.status == 200
    except OSError:
        return False


def _listening_pid() -> Optional[int]:
    """PID listening on the shop port (only used after is_up() confirmed it is the test shop)."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(f":{PORT}") and parts[3] == "LISTENING":
                    return int(parts[4])
        else:
            out = subprocess.run(["lsof", "-t", f"-iTCP:{PORT}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
            return int(out.split()[0]) if out.split() else None
    except (OSError, ValueError):
        return None
    return None


def lab_page_url() -> str:
    return f"{PUBLIC_URL}/__lab?key={lab_key()}"


class ShopServer:
    """Starts the shop: npm install (first time), npm run build (when sources changed), node server.js.
    Output lines go to on_line; state changes to on_state (both from a background thread)."""

    def __init__(self, on_line: Callable[[str], None], on_state: Callable[[str], None]):
        self.on_line, self.on_state = on_line, on_state
        self.proc: Optional[subprocess.Popen] = None
        self.state = "stopped"          # stopped | starting | running | failed
        self._lock = threading.Lock()

    def _set(self, state: str) -> None:
        self.state = state
        self.on_state(state)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.state == "starting" or self.running:
                return
            self._set("starting")
        threading.Thread(target=self._start, daemon=True, name="ecogent-test-shop").start()

    def _run_step(self, label: str, cmd: list[str]) -> bool:
        self.on_line(f"{label}: {' '.join(Path(c).name if i == 0 else c for i, c in enumerate(cmd))}")
        r = subprocess.run(cmd, cwd=str(SHOP), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "NO_COLOR": "1"})
        lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and "fnm" not in l and "Check out our docs" not in l]
        for l in lines[-8:]:
            self.on_line("  " + l)
        if r.returncode != 0:
            self.on_line(f"{label} failed (exit {r.returncode}).")
        return r.returncode == 0

    def _start(self) -> None:
        try:
            if is_up():
                self.on_line(f"A test shop is already running on port {PORT} (started outside the app).")
                self._set("running")
                return
            n, npm = node(), npm_command()
            if not n or not npm:
                self.on_line("Node.js was not found. Install Node 18+ (nodejs.org) and restart the app.")
                self._set("failed")
                return
            if needs_install() and not self._run_step("Installing packages (first start only)", [*npm, "install", "--no-audit", "--no-fund"]):
                self._set("failed")
                return
            if needs_build() and not self._run_step("Building the shop", [*npm, "run", "build"]):
                self._set("failed")
                return
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            self.proc = subprocess.Popen([n, "server.js", "--port", str(PORT)], cwd=str(SHOP), stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                         errors="replace", creationflags=flags)
            for line in self.proc.stdout:
                if line.strip():
                    self.on_line(line.rstrip())
                if "ready" in line.lower():
                    self._set("running")
            code = self.proc.wait()
            self._set("stopped" if code in (0, 1, None) or self.state == "stopped" else "failed")
        except Exception as e:  # noqa: BLE001 - report, never crash the app
            self.on_line(f"Test shop error: {type(e).__name__}: {e}")
            self._set("failed")

    def stop(self) -> None:
        if not self.running:
            pid = _listening_pid() if is_up() else None     # a shop started outside the app (or by an earlier run)
            if pid:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)] if sys.platform == "win32" else ["kill", str(pid)],
                               capture_output=True)
                self.on_line(f"Stopped the test shop that was already running (pid {pid}).")
            self._set("stopped")
            return
        self.state = "stopped"
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
        else:
            self.proc.terminate()


def check_commands() -> dict[str, list[str]]:
    return {"Shop visual invariance test": [sys.executable, "-u", str(SHOP / "check_look.py"), "--base", BASE],
            "Shop task-completion test": [sys.executable, "-u", str(SHOP / "check_flows.py"), "--base", BASE]}
