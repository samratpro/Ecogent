"""
Browser control on top of playwright_browser_manager.BrowserManager.

BrowserManager uses Playwright's sync API with one shared Playwright instance, so
every method here must be called from the same thread (Ecogent's worker thread).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable, Optional

import subprocess as _subprocess

from playwright_browser_manager import BrowserManager
from playwright_browser_manager import browser_manager as _bm_module

from .config import Settings

Log = Callable[[str], None]


# BrowserManager builds the browser command line itself and offers no way to add flags.
# Without --lang / --accept-lang a fresh profile sends the OS / IP-derived language, so
# Google shows e.g. Bengali. The shim below adds the flags only to BrowserManager's own
# Popen calls (the module's `subprocess` name is replaced, the real module is untouched).
_EXTRA_ARGS: list[str] = []


def language_args(lang: str) -> list[str]:
    lang = (lang or "").strip()
    if not lang:
        return []
    base = lang.split("-")[0]
    accept = lang if base == lang else f"{lang},{base}"
    return [f"--lang={lang}", f"--accept-lang={accept}"]


class _SubprocessShim:
    def __getattr__(self, name):
        return getattr(_subprocess, name)

    @staticmethod
    def Popen(args, *a, **kw):
        if isinstance(args, list) and args and _EXTRA_ARGS:
            args = [args[0], *_EXTRA_ARGS, *args[1:]]
        return _subprocess.Popen(args, *a, **kw)


_bm_module.subprocess = _SubprocessShim()


class BrowserError(Exception):
    pass


def _safe_console() -> None:
    """BrowserManager prints emoji; a cp1252 Windows console would raise UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


class BrowserSession:
    def __init__(self, settings: Settings, log: Log = print):
        _safe_console()
        self.settings = settings
        self.log = log
        self.manager: Optional[BrowserManager] = None
        self.page = None
        self.profile = ""
        self.headless = False
        self.lang = ""
        self.extra_wait_ms = 0          # the task's "page wait": pause after every page load

    # ------------------------------------------------------------------ lifecycle
    def _browser_path(self) -> Optional[str]:
        if self.settings.browser_path:
            return self.settings.browser_path
        return None

    def _new_manager(self) -> BrowserManager:
        path = self._browser_path()
        try:
            return BrowserManager(base_profile_dir=str(self.settings.profile_path), browser_path=path,
                                  debug_port=self.settings.debug_port)
        except (SystemExit, EOFError):
            # Auto-detection fell back to input(); use Playwright's bundled Chromium instead.
            from playwright_browser_manager.browser_manager import _get_shared_playwright
            exe = _get_shared_playwright().chromium.executable_path
            if not exe or not Path(exe).exists():
                raise BrowserError("No browser found. Set the browser path in Settings "
                                   "or run: python -m playwright install chromium")
            self.log(f"Using Playwright Chromium: {exe}")
            return BrowserManager(base_profile_dir=str(self.settings.profile_path), browser_path=exe,
                                  debug_port=self.settings.debug_port)

    @property
    def alive(self) -> bool:
        try:
            return self.page is not None and not self.page.is_closed()
        except Exception:
            return False

    def _set_language(self, lang: Optional[str]) -> str:
        """lang None = settings default; "" = system language (no flags)."""
        lang = (self.settings.browser_language if lang is None else lang).strip()
        _EXTRA_ARGS[:] = language_args(lang)
        return lang

    def ensure(self, profile: str = "", headless: Optional[bool] = None, lang: Optional[str] = None) -> None:
        headless = self.settings.headless if headless is None else headless
        want_lang = (self.settings.browser_language if lang is None else lang).strip()
        if self.alive and profile == self.profile and headless == self.headless and want_lang == self.lang:
            return
        self.close()
        self.lang = self._set_language(want_lang)
        self.manager = self._new_manager()
        timeout = self.settings.page_timeout_ms
        if profile:
            if not self.manager.profile_exists(profile):
                if profile != self.settings.default_profile:
                    raise BrowserError(f"Browser profile '{profile}' does not exist. Create it in Profiles.")
                # The default profile is created on first use; the browser fills the empty folder.
                Path(self.manager.get_profile_path(profile)).mkdir(parents=True, exist_ok=True)
                self.log(f"Created the persistent browser profile '{profile}' (cookies are kept between runs)")
            self.page = self.manager.connect_to_browser(profile_name=profile, headless=headless, timeout=timeout)
        else:
            self.page = self.manager.connect_to_browser_without_profile(headless=headless, timeout=timeout)
        self.page.set_default_timeout(timeout)
        self.profile, self.headless = profile, headless
        self.log(f"Browser ready ({'profile ' + profile if profile else 'temp profile'}, "
                 f"{'headless' if headless else 'graphics'} mode, language {self.lang or 'system'})")

    def close(self) -> None:
        if self.manager:
            try:
                self.manager.close_browser()
            except Exception as e:
                self.log(f"Browser close warning: {e}")
        self.manager, self.page = None, None

    def setup_profile(self, name: str, url: str = "", lang: Optional[str] = None) -> None:
        """Open a real browser window at `url` (destination) for manual login; returns when the user closes it."""
        self.close()
        self._set_language(lang)
        manager = self._new_manager()
        manager.setup_profile(profile_name=name, url=url or None,
                              wait_message="Log in / solve challenges, then CLOSE the browser to save the session.")

    def list_profiles(self) -> list[str]:
        p = self.settings.profile_path
        return sorted(d.name for d in p.iterdir() if d.is_dir()) if p.exists() else []

    # ------------------------------------------------------------------ page helpers
    @property
    def url(self) -> str:
        return self.page.url if self.alive else ""

    def title(self) -> str:
        try:
            return self.page.title()
        except Exception:
            return ""

    def html(self) -> str:
        for _ in range(3):
            try:
                return self.page.content()
            except Exception:
                time.sleep(1)  # page was navigating
        return self.page.content()

    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=self.settings.page_timeout_ms)
        except Exception:
            pass
        self.page.wait_for_timeout(800)

    def _follow_new_tab(self, before: int) -> None:
        pages = self.page.context.pages
        if len(pages) > before:
            self.page = pages[-1]
            self.page.set_default_timeout(self.settings.page_timeout_ms)
            self.page.bring_to_front()
            self.log("Switched to newly opened tab")

    def goto(self, url: str) -> int:
        """Open a page; returns the HTTP status (0 when unknown, e.g. about: pages)."""
        url = (url or "").strip()
        scheme = url.split(":", 1)[0].lower() if "://" in url or url.lower().startswith("about:") else ""
        if scheme and scheme not in ("http", "https", "about"):
            raise BrowserError(f"only http/https pages can be opened, not '{scheme}:' (local files go through the file tools)")
        if not scheme:
            url = "https://" + url
        try:
            resp = self.page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            # Sites redirect by script while our goto is in flight (Google after a captcha:
            # google_abuse cookie -> sgsync -> the real page). The browser did navigate; wait
            # for the redirect chain to finish instead of failing the step.
            if "interrupted by another navigation" not in str(e) and "net::ERR_ABORTED" not in str(e):
                raise
            self.log("Page redirected while loading; waiting for it to settle")
            self._settle_redirects()
            self._extra_wait()
            return 0
        self._settle()
        self._extra_wait()
        try:
            return int(resp.status) if resp is not None else 0
        except Exception:
            return 0

    def _extra_wait(self) -> None:
        if self.extra_wait_ms > 0:
            self.page.wait_for_timeout(self.extra_wait_ms)

    def _settle_redirects(self, rounds: int = 6) -> None:
        """Wait until the URL stops changing (script redirect chains)."""
        last = ""
        for _ in range(rounds):
            self._settle()
            if self.url == last:
                return
            last = self.url

    def same_page(self, url: str) -> bool:
        """The open page is `url` (host + path + query; trailing slash and fragment ignored)."""
        from urllib.parse import urlparse, parse_qsl
        if not self.alive:
            return False
        a = urlparse(url if "://" in url else "https://" + url)
        b = urlparse(self.url)
        host = lambda h: h.lower().removeprefix("www.")
        return (host(a.netloc) == host(b.netloc) and a.path.rstrip("/") == b.path.rstrip("/")
                and sorted(parse_qsl(a.query)) == sorted(parse_qsl(b.query)))

    def exists(self, selector: str) -> bool:
        try:
            loc = self.page.locator(selector)
            return loc.count() > 0 and loc.first.is_visible()
        except Exception:
            return False

    def visible_many(self, selectors: list[str]) -> list[bool]:
        """Real visibility of many CSS selectors in ONE browser round trip: catches what the HTML
        alone cannot show (CSS classes, hidden parents, closed menus). Same rule as Playwright's
        is_visible: non-empty box and not visibility:hidden. Unknown (bad selector, page busy)
        counts as visible, so this filter can only remove elements, never break a lookup."""
        if not selectors:
            return []
        try:
            res = self.page.evaluate(
                """sels => sels.map(s => {
                    let el;
                    try { el = document.querySelector(s); } catch (e) { return true; }
                    if (!el) return true;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
                })""", selectors)
            if isinstance(res, list) and len(res) == len(selectors):
                return [bool(x) for x in res]
        except Exception:
            pass
        return [True] * len(selectors)

    def element_text(self, selector: str) -> str:
        try:
            loc = self.page.locator(selector).first
            return (loc.inner_text(timeout=2000) or loc.get_attribute("value") or
                    loc.get_attribute("aria-label") or loc.get_attribute("placeholder") or "").strip()
        except Exception:
            return ""

    def describe(self, selector: str) -> dict:
        """{"tag", "text", "attrs"} of the first visible match - the element's identity, stored next
        to a cached selector so a rerun can check (and re-find) it without the LLM."""
        try:
            return self.page.locator(selector).first.evaluate(
                """el => {
                    const keep = ["id", "name", "type", "placeholder", "aria-label", "title", "role",
                                  "href", "alt", "data-testid"];
                    const attrs = {};
                    for (const k of keep) { const v = el.getAttribute(k); if (v) attrs[k] = v.slice(0, 80); }
                    const text = (el.innerText || el.value || "").replace(/\\s+/g, " ").trim().slice(0, 80);
                    return {tag: el.tagName.toLowerCase(), text, attrs};
                }""", timeout=2000) or {}
        except Exception:
            return {}

    @property
    def action_timeout(self) -> int:
        """Wait for an element to become clickable/fillable. The element was just found visible,
        so a long wait only means it is covered or disabled: fail fast and let healing act
        (page loads keep the full page_timeout_ms)."""
        return min(self.settings.page_timeout_ms, 10000)

    def click(self, selector: str) -> None:
        before = len(self.page.context.pages)
        loc = self.page.locator(selector).first
        t = self.action_timeout
        try:
            loc.scroll_into_view_if_needed(timeout=t)
        except Exception:
            pass                    # the click below reports the real problem
        url = self.page.url
        loc.click(timeout=t)
        self.page.wait_for_timeout(1000)
        self._follow_new_tab(before)
        self._settle()
        if self.page.url != url:        # the click opened another page: same pause as goto
            self._extra_wait()

    def fill(self, selector: str, value: str) -> None:
        loc = self.page.locator(selector).first
        loc.click(timeout=self.action_timeout)
        loc.fill(value, timeout=self.action_timeout)

    def press(self, key: str, selector: str = "") -> None:
        if selector:
            self.page.locator(selector).first.press(key, timeout=self.action_timeout)
        else:
            self.page.keyboard.press(key)
        self._settle()

    def select(self, selector: str, value: str) -> None:
        loc = self.page.locator(selector).first
        try:
            loc.select_option(label=value, timeout=self.action_timeout)
        except Exception:
            loc.select_option(value, timeout=self.action_timeout)

    def download(self, selector: str, folder: Path) -> Path:
        with self.page.expect_download(timeout=self.settings.page_timeout_ms) as info:
            self.page.locator(selector).first.click()
        dl = info.value
        target = Path(folder) / (dl.suggested_filename or "download")
        dl.save_as(str(target))
        return target

    def upload(self, selector: str, path: str) -> None:
        self.page.locator(selector).first.set_input_files(path, timeout=self.action_timeout)

    def scroll(self, times: int = 1) -> None:
        for _ in range(max(1, times)):
            self.page.mouse.wheel(0, 2500)
            self.page.wait_for_timeout(900)

    def wait_for(self, selector: str, timeout_ms: int = 15000) -> None:
        self.page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)

    def screenshot(self, path: Path) -> None:
        self.page.screenshot(path=str(path), full_page=True)

    def save_storage(self, path: Path) -> None:
        self.page.context.storage_state(path=str(path))
