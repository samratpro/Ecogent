"""
Public lab server for a VPS: the same four sites as bench/lab/server.py, but safe for many visitors.

  - every visitor (browser / agent context) gets its own LabState via a `lab_sid` cookie, so carts,
    applications, CRM logins, notes and deals never mix between testers
  - the drift level (0-4) and seed are per visitor too, chosen by URL or by one click:
        https://lab.example.com/shop/?lab_level=2&lab_seed=1   sets the level, then redirects to /shop/
    the choice is kept in cookies, so every later page and form uses the same version
  - a small switch bar at the bottom of every page changes the version of the page you are on
    (hide it with ?lab_bar=0, show again with ?lab_bar=1)
  - /lab/  control page: current version, reset, what the site recorded, the task prompts, and live
    scoring of the automation tasks (scraping / analysis need the agent's output file: use
    bench/lab/serve.py or drift_bench.py for those)
  - pages are marked noindex and robots.txt disallows everything, so search engines leave it alone

Run behind nginx (see bench/lab/deploy/):
    python -m bench.lab.public --host 127.0.0.1 --port 8790
"""

from __future__ import annotations

import argparse
import html
import http.server
import json
import secrets
import threading
import time
from collections import OrderedDict
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode, urlsplit

from . import drift, sites
from .tasks import TASKS, USER_INFO

MAX_SESSIONS = 2000              # least recently used visitors are dropped beyond this
IDLE_SECONDS = 12 * 3600
MAX_BODY = 64 * 1024
LAB_PARAMS = ("lab_level", "lab_seed", "lab_bar")
COOKIE_AGE = 30 * 86400


class Sessions:
    def __init__(self):
        self._d: OrderedDict[str, tuple[sites.LabState, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, sid: str | None) -> tuple[str, sites.LabState, bool]:
        """(sid, state, is_new)."""
        now = time.time()
        with self._lock:
            if sid and sid in self._d:
                state, _ = self._d.pop(sid)
                self._d[sid] = (state, now)
                return sid, state, False
            while self._d:                                   # expire idle / overflow
                k, (_, seen) = next(iter(self._d.items()))
                if len(self._d) < MAX_SESSIONS and now - seen < IDLE_SECONDS:
                    break
                self._d.popitem(last=False)
            sid = secrets.token_hex(12)
            self._d[sid] = (sites.LabState(), now)
            return sid, self._d[sid][0], True

    def __len__(self):
        return len(self._d)


def _int(v, lo, hi, default):
    try:
        return min(hi, max(lo, int(v)))
    except (TypeError, ValueError):
        return default


def _safe_next(p: str) -> str:
    return p if p.startswith("/") and not p.startswith("//") and "\\" not in p else "/"


BAR_CSS = ("position:fixed;left:0;right:0;bottom:0;z-index:2147483000;background:#111;color:#eee;"
           "font:12px/1.2 system-ui,sans-serif;padding:6px 10px;display:flex;gap:6px;align-items:center;"
           "flex-wrap:wrap;opacity:.92")


def switch_bar(path_qs: str, level: int, seed: int) -> str:
    sep = "&" if "?" in path_qs else "?"
    links = []
    for lv, name in drift.LEVELS.items():
        style = "background:#fff;color:#111" if lv == level else "color:#ddd"
        links.append(f'<a href="{html.escape(path_qs + sep + "lab_level=" + str(lv))}" '
                     f'style="{style};padding:2px 6px;border-radius:3px;text-decoration:none">{lv} {name}</a>')
    return (f'<div data-lab-bar="1" style="{BAR_CSS}"><b>Lab version</b> {"".join(links)}'
            f'<span style="margin-left:8px">seed {seed}</span>'
            f'<a href="/lab/" style="color:#9cf;margin-left:auto">control</a>'
            f'<a href="{html.escape(path_qs + sep + "lab_bar=0")}" style="color:#999">hide</a></div>')


def control_page(base: str, state: sites.LabState, level: int, seed: int, sid: str, n_sessions: int,
                 scored: str = "") -> str:
    e = html.escape
    lv = "".join(f'<a class="b{" on" if k == level else ""}" href="/lab/?lab_level={k}">{k} · {v}</a>'
                 for k, v in drift.LEVELS.items())
    rec = {k: getattr(state, k) for k in ("cart", "saved", "applications", "notes", "deals")}
    rows = []
    for t in TASKS:
        prompt = t.prompt.format(base=base)
        if "my full name" in prompt:
            prompt += f" My full name is {USER_INFO['full_name']} and my email is {USER_INFO['email']}."
        score = (f'<form method="post" action="/lab/score"><input type="hidden" name="task" value="{e(t.name)}">'
                 f'<button>score</button></form>') if t.type == "automation" else "<small>needs output file</small>"
        rows.append(f"<tr><td><b>{e(t.name)}</b><br><small>{e(t.type)}</small></td><td>{e(prompt)}</td>"
                    f"<td>{score}</td></tr>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Lab control</title><style>
body{{font:14px/1.45 system-ui,sans-serif;margin:0;background:#fafafa;color:#111}}
.w{{max-width:1000px;margin:auto;padding:16px}} h1{{margin:.2em 0}}
.b{{display:inline-block;padding:6px 10px;margin:2px;border:1px solid #bbb;border-radius:4px;color:#111;text-decoration:none;background:#fff}}
.b.on{{background:#111;color:#fff}} table{{border-collapse:collapse;width:100%;background:#fff}}
td{{border-bottom:1px solid #eee;padding:6px;vertical-align:top}} pre{{background:#fff;padding:8px;overflow:auto;border:1px solid #eee}}
.note{{background:#fff8d6;padding:8px;border:1px solid #ecd97a}}
</style></head><body><div class="w">
<h1>Ecogent benchmark lab</h1>
<p>Sites: <a href="/shop/">shop</a> · <a href="/papers/">papers</a> · <a href="/jobs/">jobs</a> · <a href="/crm/login">crm</a>
 &nbsp; <small>visitor {e(sid[:6])}…, {n_sessions} active</small></p>
<h3>Version (drift level) for this browser</h3><p>{lv}</p>
<form method="get" action="/lab/">Seed <input name="lab_seed" value="{seed}" size="4"> <button>set seed</button></form>
<p><small>Give an agent a fixed version through the start URL, e.g.
<code>{e(base)}/shop/?lab_level=3&amp;lab_seed=1</code>, so a fresh browser starts on it.</small></p>
<h3>Recorded by the site</h3>
<form method="post" action="/lab/reset"><button>reset my state</button></form>
{f'<p class="note">{e(scored)}</p>' if scored else ""}
<pre>{e(json.dumps(rec, indent=1, default=str))}</pre>
<h3>Tasks</h3><table>{"".join(rows)}</table>
</div></body></html>"""


def make_handler(sessions: Sessions, public_base: str | None):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "EcogentLab/1"
        sys_version = ""

        def log_message(self, fmt, *a):
            pass

        def _base(self) -> str:
            if public_base:
                return public_base.rstrip("/")
            proto = self.headers.get("X-Forwarded-Proto", "http")
            return f"{proto}://{self.headers.get('Host', 'localhost')}"

        def _send(self, code: int, body: str, headers: dict, cookies: list[str], ctype="text/html; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            for c in cookies:
                self.send_header("Set-Cookie", c)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _serve(self, method: str):
            u = urlsplit(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, "<h1>Too large</h1>", {}, [])
            body = self.rfile.read(n) if n else b""
            raw_cookie = self.headers.get("Cookie", "")
            jar = SimpleCookie()
            try:
                jar.load(raw_cookie)
            except Exception:
                pass
            ck = {k: v.value for k, v in jar.items()}
            sid, state, new = sessions.get(ck.get("lab_sid"))
            set_cookies = []
            if new:
                set_cookies.append(f"lab_sid={sid}; Path=/; Max-Age={COOKIE_AGE}; HttpOnly; SameSite=Lax")
            level = _int(ck.get("lab_level"), 0, max(drift.LEVELS), 0)
            seed = _int(ck.get("lab_seed"), 1, 10**6, 1)
            bar = ck.get("lab_bar", "1") != "0"

            if u.path == "/robots.txt":
                return self._send(200, "User-agent: *\nDisallow: /\n", {}, set_cookies, "text/plain")
            if u.path == "/healthz":
                return self._send(200, "ok", {}, [], "text/plain")

            # ?lab_level= / ?lab_seed= / ?lab_bar= : remember the choice, redirect to the clean URL
            query = parse_qs(u.query, keep_blank_values=True)
            if method == "GET" and any(p in query for p in LAB_PARAMS):
                if "lab_level" in query:
                    level = _int(query["lab_level"][0], 0, max(drift.LEVELS), level)
                    set_cookies.append(f"lab_level={level}; Path=/; Max-Age={COOKIE_AGE}; SameSite=Lax")
                if "lab_seed" in query:
                    seed = _int(query["lab_seed"][0], 1, 10**6, seed)
                    set_cookies.append(f"lab_seed={seed}; Path=/; Max-Age={COOKIE_AGE}; SameSite=Lax")
                if "lab_bar" in query:
                    set_cookies.append(f"lab_bar={'0' if query['lab_bar'][0] == '0' else '1'}; Path=/; "
                                       f"Max-Age={COOKIE_AGE}; SameSite=Lax")
                rest = {k: v for k, v in query.items() if k not in LAB_PARAMS}
                clean = u.path + ("?" + urlencode(rest, doseq=True) if rest else "")
                return self._send(303, "", {"Location": _safe_next(clean)}, set_cookies)

            # control page
            if u.path.rstrip("/") == "/lab" or u.path.startswith("/lab/"):
                scored = ""
                if method == "POST" and u.path == "/lab/reset":
                    state.reset()
                    return self._send(303, "", {"Location": "/lab/"}, set_cookies)
                if method == "POST" and u.path == "/lab/score":
                    form = parse_qs(body.decode("utf-8", "replace"))
                    name = (form.get("task") or [""])[0]
                    task = next((t for t in TASKS if t.name == name and t.type == "automation"), None)
                    if task:
                        try:
                            r = task.oracle(None, state)
                            scored = (f"{name}: {'SUCCESS' if r['success'] else 'FAIL'}  precision {r['precision']}"
                                      f"  recall {r['recall']}  ({r.get('detail', '')})")
                        except Exception as e:      # noqa: BLE001
                            scored = f"{name}: scoring error {e}"
                return self._send(200, control_page(self._base(), state, level, seed, sid, len(sessions), scored),
                                  {}, set_cookies)

            # the lab sites, at this visitor's version
            try:
                code, page, headers = sites.route(method, u.path, query, state, body, raw_cookie)
                fragment = headers.pop("X-Fragment", None) is not None
                page = drift.apply(page, level, seed, u.path + "?" + u.query, fragment=fragment)
            except Exception:              # noqa: BLE001
                code, page, headers = 500, "<html><body><h1>Lab error</h1></body></html>", {}
            site_cookie = headers.pop("Set-Cookie", None)
            if site_cookie:
                set_cookies.append(site_cookie)
            if code == 200 and bar and not fragment and "</body>" in page:
                path_qs = u.path + ("?" + u.query if u.query else "")
                page = page.replace("</body>", switch_bar(path_qs, level, seed) + "</body>", 1)
            return self._send(code, page, headers, set_cookies)

        def do_GET(self):
            self._serve("GET")

        def do_HEAD(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--public-base", default=None,
                    help="URL shown in task prompts, e.g. https://lab.example.com (default: from the Host header)")
    args = ap.parse_args()
    httpd = http.server.ThreadingHTTPServer((args.host, args.port), make_handler(Sessions(), args.public_base))
    httpd.daemon_threads = True
    print(f"Ecogent public lab on http://{args.host}:{args.port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
