"""
Local HTTP server for the benchmark lab. Serves the three sites with the current drift level
applied to every HTML response; the runner changes level / seed and resets the recorded state
between runs. Responses are never cached (a rerun must see the new drift level).
"""

from __future__ import annotations

import http.server
import threading
from urllib.parse import parse_qs, urlsplit

from . import drift, sites


class LabServer:
    def __init__(self, port: int = 8790, host: str = "127.0.0.1"):
        self.state = sites.LabState()
        state = self.state

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self, method: str):
                u = urlsplit(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                try:
                    code, html, headers = sites.route(method, u.path, parse_qs(u.query), state, body,
                                                      self.headers.get("Cookie", ""))
                    fragment = headers.pop("X-Fragment", None) is not None
                    html = drift.apply(html, state.level, state.seed, u.path + "?" + u.query, fragment=fragment)
                except Exception as e:      # noqa: BLE001 - a lab bug must show, not kill the server
                    code, html, headers = 500, f"<html><body><h1>Lab error</h1><pre>{e}</pre></body></html>", {}
                data = html.encode("utf-8")
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._serve("GET")

            def do_POST(self):
                self._serve("POST")

        self.httpd = http.server.ThreadingHTTPServer((host, port), Handler)
        self.base = f"http://{host}:{port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def set(self, level: int, seed: int) -> None:
        self.state.level, self.state.seed = int(level), int(seed)

    def reset(self) -> None:
        self.state.reset()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
