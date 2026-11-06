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

from playwright_browser_manager import BrowserManager

from .config import Settings

Log = Callable[[str], None]


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

    def ensure(self, profile: str = "", headless: Optional[bool] = None) -> None:
        headless = self.settings.headless if headless is None else headless
        if self.alive and profile == self.profile and headless == self.headless:
            return
        self.close()
        self.manager = self._new_manager()
        timeout = self.settings.page_timeout_ms
        if profile:
            if not self.manager.profile_exists(profile):
                raise BrowserError(f"Browser profile '{profile}' does not exist. Create it in Profiles.")
            self.page = self.manager.connect_to_browser(profile_name=profile, headless=headless, timeout=timeout)
        else:
            self.page = self.manager.connect_to_browser_without_profile(headless=headless, timeout=timeout)
        self.page.set_default_timeout(timeout)
        self.profile, self.headless = profile, headless
        self.log(f"Browser ready ({'profile ' + profile if profile else 'temp profile'}, "
                 f"{'headless' if headless else 'graphics'} mode)")

    def close(self) -> None:
        if self.manager:
            try:
                self.manager.close_browser()
            except Exception as e:
                self.log(f"Browser close warning: {e}")
        self.manager, self.page = None, None

    def setup_profile(self, name: str, url: str = "") -> None:
        """Open a real browser window for manual login; returns when the user closes it."""
        self.close()
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

    def goto(self, url: str) -> None:
        url = (url or "").strip()
        scheme = url.split(":", 1)[0].lower() if "://" in url or url.lower().startswith("about:") else ""
        if scheme and scheme not in ("http", "https", "about"):
            raise BrowserError(f"only http/https pages can be opened, not '{scheme}:' (local files go through the file tools)")
        if not scheme:
            url = "https://" + url
        self.page.goto(url, wait_until="domcontentloaded")
        self._settle()

    def exists(self, selector: str) -> bool:
        try:
            loc = self.page.locator(selector)
            return loc.count() > 0 and loc.first.is_visible()
        except Exception:
            return False

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

    def click(self, selector: str) -> None:
        before = len(self.page.context.pages)
        loc = self.page.locator(selector).first
        loc.scroll_into_view_if_needed()
        loc.click()
        self.page.wait_for_timeout(1000)
        self._follow_new_tab(before)
        self._settle()

    def fill(self, selector: str, value: str) -> None:
        loc = self.page.locator(selector).first
        loc.click()
        loc.fill(value)

    def press(self, key: str, selector: str = "") -> None:
        if selector:
            self.page.locator(selector).first.press(key)
        else:
            self.page.keyboard.press(key)
        self._settle()

    def select(self, selector: str, value: str) -> None:
        loc = self.page.locator(selector).first
        try:
            loc.select_option(label=value)
        except Exception:
            loc.select_option(value)

    def download(self, selector: str, folder: Path) -> Path:
        with self.page.expect_download(timeout=self.settings.page_timeout_ms) as info:
            self.page.locator(selector).first.click()
        dl = info.value
        target = Path(folder) / (dl.suggested_filename or "download")
        dl.save_as(str(target))
        return target

    def upload(self, selector: str, path: str) -> None:
        self.page.locator(selector).first.set_input_files(path)

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
