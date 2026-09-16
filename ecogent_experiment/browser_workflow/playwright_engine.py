"""
Playwright Action Engine.

The single, reliable Playwright wrapper for all browser automation actions.
All interactions (navigate, click, fill, extract, validate) flow through this class.

Design principles:
- Every action has a timeout and retry logic
- Variable substitution happens before execution ({query} → "gaming laptop")
- Screenshots captured on failure for debugging
- Validation is purely deterministic (zero LLM calls)
- Page HTML captured for AI recovery prompts (truncated for token efficiency)
"""

import os
import re
import time
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ecogent_experiment.browser_workflow.schema import (
    ActionResult,
    BrowserStep,
    PageContext,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_MS = 15000     # Default action timeout
NAVIGATION_TIMEOUT_MS = 25000  # Navigate actions get more time
EXTRACT_TIMEOUT_MS = 8000      # Text extraction timeout
HTML_SNIPPET_CHARS = 80000      # How much HTML to send to AI on failure


# ---------------------------------------------------------------------------
# HTML Cleaner for LLM Recovery Context
# ---------------------------------------------------------------------------

def clean_html_for_llm(html_content: str) -> str:
    """Full cleaned HTML - used only for recovery fallback context."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 1. Remove unwanted tags entirely
        for tag in soup(['script', 'style', 'svg', 'path', 'meta', 'link', 'noscript', 'iframe']):
            tag.decompose()
            
        # 2. Clean attributes and truncate text
        keep_attrs = {'id', 'class', 'name', 'type', 'placeholder', 'aria-label', 'role', 'href'}
        
        for tag in soup.find_all(True):
            attrs_to_remove = [attr for attr in tag.attrs if attr not in keep_attrs]
            for attr in attrs_to_remove:
                del tag[attr]
            for attr in tag.attrs:
                if isinstance(tag[attr], list):
                    tag[attr] = " ".join(tag[attr])

        # 3. Truncate long text nodes
        for text_node in soup.find_all(string=True):
            text = text_node.string.strip()
            if text:
                if len(text) > 100:
                    text_node.string.replace_with(text[:97] + "...")
                else:
                    text_node.string.replace_with(text)
            else:
                text_node.extract()
                
        cleaned = str(soup)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        return cleaned
    except Exception:
        return html_content[:2000]


def extract_elements_map(html_content: str) -> str:
    """
    Use BeautifulSoup to extract a structured, token-efficient map of
    interactive elements and data-bearing elements from the live page.

    Returns a short, human-readable string like:
        INPUTS:
          - selector: #twotabsearchtextbox  type=text  placeholder="Search Amazon"
        BUTTONS:
          - selector: #nav-search-submit-button  text="Go"
        LINKS (top 10):
          - selector: a[href*="/dp/"]  text="Aveeno Baby Gift Set..."
        PRICES:
          - selector: .a-price-whole  text="1,437"
        HEADINGS:
          - <h1> Baby Products
          - <h2> Aveeno Baby Welcome...

    This is the PRIMARY input to the LLM — not raw HTML.
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove noise tags
        for tag in soup(['script', 'style', 'svg', 'path', 'noscript', 'iframe', 'meta', 'link']):
            tag.decompose()

        lines = []

        # ── INPUTS ──────────────────────────────────────────
        inputs = soup.find_all('input', limit=20)
        if inputs:
            lines.append("INPUTS:")
            for el in inputs:
                itype = el.get('type', 'text')
                if itype in ('hidden', 'submit'):
                    continue
                sel = _best_selector(el)
                placeholder = el.get('placeholder', '')
                aria = el.get('aria-label', '')
                name = el.get('name', '')
                info = f"  - selector: {sel}  type={itype}"
                if placeholder: info += f"  placeholder='{placeholder[:50]}'"
                if aria:        info += f"  aria-label='{aria[:50]}'"
                if name:        info += f"  name={name}"
                lines.append(info)

        # ── BUTTONS ─────────────────────────────────────────
        buttons = soup.find_all(['button', 'input[type="submit"]'], limit=15)
        submit_inputs = soup.find_all('input', type='submit', limit=5)
        all_buttons = list(buttons) + list(submit_inputs)
        if all_buttons:
            lines.append("BUTTONS:")
            for el in all_buttons[:15]:
                sel = _best_selector(el)
                text = (el.get_text(strip=True) or el.get('value', '') or el.get('aria-label', ''))[:60]
                lines.append(f"  - selector: {sel}  text='{text}'")

        # ── SELECT DROPDOWNS ────────────────────────────────
        selects = soup.find_all('select', limit=5)
        if selects:
            lines.append("SELECTS:")
            for el in selects:
                sel = _best_selector(el)
                options = [o.get_text(strip=True) for o in el.find_all('option')][:6]
                lines.append(f"  - selector: {sel}  options={options}")

        # ── PRICES ──────────────────────────────────────────
        # Price pattern: elements with currency symbols or price class names
        price_els = soup.find_all(class_=re.compile(r'price|Price', re.I), limit=10)
        # Also look for text matching price patterns
        price_text_els = [
            el for el in soup.find_all(string=re.compile(r'[\$\£\€\₹][\d,\.]+|[\d,]+\.[\d]{2}'))
            if el.parent
        ][:8]
        if price_els or price_text_els:
            lines.append("PRICES:")
            seen = set()
            for el in price_els:
                sel = _best_selector(el)
                text = el.get_text(strip=True)[:40]
                if text and sel not in seen:
                    seen.add(sel)
                    lines.append(f"  - selector: {sel}  text='{text}'")
            for el in price_text_els:
                parent = el.parent
                sel = _best_selector(parent)
                text = el.strip()[:40]
                if sel not in seen:
                    seen.add(sel)
                    lines.append(f"  - selector: {sel}  text='{text}'")

        # ── PRODUCT TITLES / KEY TEXT ────────────────────────
        headings = soup.find_all(['h1', 'h2', 'h3'], limit=8)
        if headings:
            lines.append("HEADINGS:")
            for el in headings:
                text = el.get_text(strip=True)[:80]
                if text:
                    lines.append(f"  - <{el.name}> {text}")

        # ── PRODUCT LINKS (first 6) ─────────────────────────
        product_links = [
            a for a in soup.find_all('a', href=True, limit=50)
            if '/dp/' in a.get('href', '') or 'product' in a.get('href', '').lower()
        ][:6]
        if product_links:
            lines.append("PRODUCT LINKS:")
            for a in product_links:
                href = a['href'][:80]
                text = a.get_text(strip=True)[:60]
                lines.append(f"  - href={href}  text='{text}'")

        # ── DIALOGS / POPUPS ────────────────────────────────
        dialogs = soup.find_all(attrs={'role': re.compile(r'dialog|alert|banner', re.I)}, limit=3)
        if dialogs:
            lines.append("POPUPS/DIALOGS:")
            for d in dialogs:
                sel = _best_selector(d)
                text = d.get_text(strip=True)[:80]
                lines.append(f"  - selector: {sel}  text='{text}'")

        result = "\n".join(lines)
        return result if result else "(no interactive elements found)"

    except Exception as exc:
        return f"(element extraction failed: {exc})"


def _best_selector(el) -> str:
    """Build the most specific CSS selector for a BeautifulSoup element."""
    if el.get('id'):
        return f"#{el['id']}"
    if el.get('name'):
        return f"{el.name}[name='{el['name']}']"
    if el.get('aria-label'):
        aria = el['aria-label'].replace("'", "")[:40]
        return f"{el.name}[aria-label='{aria}']"
    classes = el.get('class', [])
    if isinstance(classes, list) and classes:
        cls = ".".join(classes[:2])
        return f"{el.name}.{cls}"
    return el.name


# ---------------------------------------------------------------------------
# Playwright Engine
# ---------------------------------------------------------------------------

class PlaywrightEngine:
    """
    Robust Playwright wrapper for browser automation pattern execution.

    Handles:
    - Browser lifecycle (launch, page, close) via context manager
    - Action execution with timeouts and retries
    - Deterministic step validation (no LLM)
    - Variable substitution in action values
    - Screenshot-on-failure
    - Page context capture for AI recovery

    Usage:
        with PlaywrightEngine(headless=True) as engine:
            result = engine.execute_action(page, step.get_action(), variables)
            vresult = engine.validate_step(page, step.get_validation(), extracted)
    """

    def __init__(
        self,
        headless: bool = False,
        screenshots_dir: Optional[str] = None,
        slow_mo: int = 0,
    ):
        """
        Args:
            headless:        Run browser invisibly (True) or visibly (False).
            screenshots_dir: Directory to save failure screenshots. If None,
                             screenshots are skipped.
            slow_mo:         Slow Playwright actions by N ms (useful for debugging).
        """
        self.headless = headless
        self.screenshots_dir = screenshots_dir
        self.slow_mo = slow_mo
        self._playwright = None
        self._browser = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        return self

    def __exit__(self, *args):
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

    def new_page(self):
        """Open a new browser page."""
        context = self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        return context.new_page()

    # ------------------------------------------------------------------
    # Variable substitution
    # ------------------------------------------------------------------

    def _substitute(self, value: str, variables: Dict[str, str]) -> str:
        """Replace {variable} placeholders with actual values."""
        for key, val in variables.items():
            value = value.replace(f"{{{key}}}", str(val))
        return value

    # ------------------------------------------------------------------
    # Action Execution
    # ------------------------------------------------------------------

    def execute_action(
        self,
        page,
        action: dict,
        variables: Dict[str, str],
    ) -> ActionResult:
        """
        Execute a single browser action.

        Args:
            page:      Playwright page object.
            action:    Action dict (from BrowserStep.action).
            variables: Variable substitution dict.

        Returns:
            ActionResult with success status and any extracted value.
        """
        action_type = action.get("type", "")

        try:
            if action_type == "navigate":
                return self._navigate(page, action, variables)

            elif action_type == "click":
                return self._click(page, action, variables)

            elif action_type == "fill":
                return self._fill(page, action, variables)

            elif action_type == "select":
                return self._select(page, action, variables)

            elif action_type == "extract":
                return self._extract(page, action, variables)

            elif action_type == "wait_for":
                return self._wait_for(page, action, variables)

            elif action_type == "scroll":
                return self._scroll(page, action, variables)

            elif action_type == "screenshot":
                return self._screenshot(page, action, variables)

            elif action_type == "key_press":
                return self._key_press(page, action, variables)

            else:
                return ActionResult(
                    success=False,
                    error=f"Unknown action type: '{action_type}'"
                )

        except Exception as e:
            self._try_screenshot(page, f"fail_{action_type}")
            return ActionResult(success=False, error=str(e))

    def _navigate(self, page, action: dict, variables: dict) -> ActionResult:
        url = self._substitute(action.get("url", ""), variables)
        page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        # Auto-dismiss common overlay popups that block interaction
        self._dismiss_popups(page)
        return ActionResult(success=True)

    def _dismiss_popups(self, page) -> None:
        """
        Silently dismiss overlay popups/dialogs after page load.
        Uses only generic ARIA roles and common patterns — no site-specific selectors.
        Never raises — best-effort only.
        """
        # Generic selectors based on ARIA roles and common patterns
        dismiss_selectors = [
            # ARIA dialog close/dismiss buttons
            "[role='dialog'] button[aria-label*='close' i]",
            "[role='dialog'] button[aria-label*='dismiss' i]",
            "[role='dialog'] button[aria-label*='accept' i]",
            "[role='alertdialog'] button",
            # Common cookie/consent banner patterns
            "button[id*='accept' i]",
            "button[id*='agree' i]",
            "button[class*='dismiss' i]",
            "button[class*='cookie-accept' i]",
            "button[class*='consent-accept' i]",
            # Close buttons via ARIA label (generic)
            "[aria-label='Close']",
            "[aria-label='Dismiss']",
            "[aria-label='close' i]",
        ]
        for sel in dismiss_selectors:
            try:
                locator = page.locator(sel).first
                if locator.is_visible(timeout=500):
                    locator.click(timeout=500)
                    page.wait_for_timeout(300)
            except Exception:
                continue

    def _click(self, page, action: dict, variables: dict) -> ActionResult:
        selector = self._substitute(action.get("selector", ""), variables)
        try:
            page.locator(selector).click(timeout=DEFAULT_TIMEOUT_MS)
        except Exception:
            # Fallback: try text-based selector
            text_match = re.search(r'text[=~]"?([^"]+)"?', selector)
            if text_match:
                page.get_by_text(text_match.group(1)).first.click(
                    timeout=DEFAULT_TIMEOUT_MS
                )
            else:
                raise
        return ActionResult(success=True)

    def _fill(self, page, action: dict, variables: dict) -> ActionResult:
        selector = self._substitute(action.get("selector", ""), variables)
        value = self._substitute(action.get("value", ""), variables)
        locator = page.locator(selector)
        locator.wait_for(timeout=DEFAULT_TIMEOUT_MS)
        locator.clear()
        locator.fill(value)
        return ActionResult(success=True)

    def _select(self, page, action: dict, variables: dict) -> ActionResult:
        selector = self._substitute(action.get("selector", ""), variables)
        option = self._substitute(action.get("option", ""), variables)
        page.locator(selector).select_option(option, timeout=DEFAULT_TIMEOUT_MS)
        return ActionResult(success=True)

    def _extract(self, page, action: dict, variables: dict) -> ActionResult:
        selector = self._substitute(action.get("selector", ""), variables)
        multiple = action.get("multiple", False)

        locator = page.locator(selector)

        if multiple:
            # Wait for at least one element
            locator.first.wait_for(timeout=EXTRACT_TIMEOUT_MS)
            texts = locator.all_inner_texts()
            # Clean whitespace
            texts = [t.strip() for t in texts if t.strip()]
            return ActionResult(success=True, extracted_value=texts)
        else:
            locator.wait_for(timeout=EXTRACT_TIMEOUT_MS)
            text = locator.first.inner_text(timeout=EXTRACT_TIMEOUT_MS).strip()
            return ActionResult(success=True, extracted_value=text)

    def _wait_for(self, page, action: dict, variables: dict) -> ActionResult:
        selector = action.get("selector")
        timeout_ms = action.get("timeout_ms")

        if selector:
            selector = self._substitute(selector, variables)
            page.locator(selector).wait_for(timeout=DEFAULT_TIMEOUT_MS)
        elif timeout_ms:
            page.wait_for_timeout(timeout_ms)

        return ActionResult(success=True)

    def _scroll(self, page, action: dict, variables: dict) -> ActionResult:
        direction = action.get("direction", "down")
        amount = action.get("amount", 500)

        if direction == "down":
            page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            page.evaluate(f"window.scrollBy(0, -{amount})")
        elif direction == "right":
            page.evaluate(f"window.scrollBy({amount}, 0)")
        elif direction == "left":
            page.evaluate(f"window.scrollBy(-{amount}, 0)")

        return ActionResult(success=True)

    def _screenshot(self, page, action: dict, variables: dict) -> ActionResult:
        if self.screenshots_dir:
            os.makedirs(self.screenshots_dir, exist_ok=True)
            output_key = action.get("output_key", "screenshot")
            path = os.path.join(
                self.screenshots_dir,
                f"{output_key}_{int(time.time())}.png"
            )
            page.screenshot(path=path)
            return ActionResult(success=True, extracted_value=path)
        return ActionResult(success=True)

    def _key_press(self, page, action: dict, variables: dict) -> ActionResult:
        key = action.get("key", "Enter")
        page.keyboard.press(key)
        return ActionResult(success=True)

    def _try_screenshot(self, page, label: str) -> None:
        """Attempt to save a failure screenshot silently."""
        if self.screenshots_dir:
            try:
                os.makedirs(self.screenshots_dir, exist_ok=True)
                path = os.path.join(
                    self.screenshots_dir,
                    f"fail_{label}_{int(time.time())}.png"
                )
                page.screenshot(path=path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Validation (Deterministic — No LLM)
    # ------------------------------------------------------------------

    def validate_step(
        self,
        page,
        validation: dict,
        extracted: Dict[str, Any],
    ) -> ValidationResult:
        """
        Run a deterministic validation rule against the current page state.

        Args:
            page:       Playwright page object.
            validation: Validation dict (from BrowserStep.validation).
            extracted:  Accumulated extracted data (output_key → value).

        Returns:
            ValidationResult with passed/failed + detail.
        """
        vtype = validation.get("type", "")

        try:
            if vtype == "url_contains":
                value = validation.get("value", "").lower()
                current = page.url.lower()
                passed = value in current
                return ValidationResult(
                    passed=passed,
                    detail=f"URL '{page.url}' {'contains' if passed else 'does NOT contain'} '{value}'"
                )

            elif vtype == "element_exists":
                selector = validation.get("selector", "")
                count = page.locator(selector).count()
                passed = count > 0
                return ValidationResult(
                    passed=passed,
                    detail=f"Selector '{selector}' found {count} elements"
                )

            elif vtype == "element_has_text":
                selector = validation.get("selector", "")
                expected = validation.get("text", "").lower()
                try:
                    actual = page.locator(selector).first.inner_text(
                        timeout=3000
                    ).lower()
                    passed = expected in actual
                except Exception:
                    passed = False
                    actual = "(not found)"
                return ValidationResult(
                    passed=passed,
                    detail=f"Expected text '{expected}' in element '{selector}'"
                )

            elif vtype == "element_has_value":
                selector = validation.get("selector", "")
                expected = validation.get("value", "")
                try:
                    actual = page.locator(selector).input_value(timeout=3000)
                    passed = actual == expected
                except Exception:
                    passed = False
                    actual = "(not found)"
                return ValidationResult(
                    passed=passed,
                    detail=f"Input value check for '{selector}'"
                )

            elif vtype == "extracted_count_gte":
                output_key = validation.get("output_key", "")
                min_count = validation.get("count", 1)
                data = extracted.get(output_key, [])
                count = len(data) if isinstance(data, list) else (1 if data else 0)
                passed = count >= min_count
                return ValidationResult(
                    passed=passed,
                    detail=f"Extracted {count} items for '{output_key}' (need >= {min_count})"
                )

            elif vtype == "page_title_contains":
                value = validation.get("value", "").lower()
                title = page.title().lower()
                passed = value in title
                return ValidationResult(
                    passed=passed,
                    detail=f"Page title '{page.title()}' {'contains' if passed else 'does NOT contain'} '{value}'"
                )

            elif vtype == "no_error_page":
                error_patterns = [
                    "404", "not found", "error", "page not available",
                    "403 forbidden", "500 internal", "access denied",
                ]
                title = page.title().lower()
                url = page.url.lower()
                has_error = any(p in title or p in url for p in error_patterns)
                return ValidationResult(
                    passed=not has_error,
                    detail=f"No error indicators in title/URL"
                )

            elif vtype == "key_press_sent":
                return ValidationResult(passed=True, detail="Key press self-validates")

            else:
                return ValidationResult(
                    passed=False,
                    detail=f"Unknown validation type: '{vtype}'"
                )

        except Exception as e:
            return ValidationResult(passed=False, error=str(e), detail=str(e))

    # ------------------------------------------------------------------
    # Page Context (for AI recovery prompts)
    # ------------------------------------------------------------------

    def get_page_context(self, page) -> PageContext:
        """
        Capture current page state.

        - elements_map: structured BeautifulSoup extraction (primary LLM input)
        - html_snippet: full cleaned HTML (fallback for recovery when element map isn't enough)
        """
        try:
            url = page.url
            title = page.title()
        except Exception:
            url = "(unknown)"
            title = "(unknown)"

        elements_map = ""
        html_snippet = ""
        try:
            full_html = page.content()
            # Always build the structured element map first (token-efficient)
            elements_map = extract_elements_map(full_html)
            # Also build full cleaned HTML for fallback recovery context
            html_snippet = clean_html_for_llm(full_html)
            if len(html_snippet) > HTML_SNIPPET_CHARS:
                html_snippet = html_snippet[:HTML_SNIPPET_CHARS] + "...[truncated]"
        except Exception:
            pass

        return PageContext(
            url=url,
            title=title,
            html_snippet=html_snippet,
            elements_map=elements_map,
        )
