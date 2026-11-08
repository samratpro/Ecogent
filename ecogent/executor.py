"""
Step executor.

Runs current_task.json step by step:
  * element lookup (no LLM first):
      cached selector + identity check (tag, stable attributes, text) -> stored alternate
      locators -> local re-match of the remembered element among the page's elements ->
      the obvious candidate (only one fits / clear winner)
    and only then the LLM: probable elements -> broader area -> page outline
  * failed steps are healed by the LLM (bounded per step and per run) and saved back
  * a per-run token budget asks the user before going over
  * captcha / login walls pause for the user
  * everything is recorded in plan.json (execution) and steps.json (log)
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from . import page_reader as pr
from . import prompts, toolbox
from .bridge import HeadlessBridge, UIBridge
from .browser import BrowserSession
from .config import Settings
from .llm import BudgetExceeded, LLMError, LLMRouter
from .storage import ChatSession, now_iso
from .tools import FileTools


class StopRequested(Exception):
    pass


class StepFailed(Exception):
    pass


class NeedsUser(StepFailed):
    def __init__(self, message: str, in_browser: bool = True):
        super().__init__(message)
        self.in_browser = in_browser      # the human must act in the browser window


class NoHeal(StepFailed):
    """A failure that step healing cannot fix (e.g. the scraping pattern budget is used up)."""


@dataclass
class RunStats:
    steps_ok: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    cache_hits: int = 0
    local_heals: int = 0        # changed elements re-found without the LLM
    local_picks: int = 0        # new elements chosen without the LLM (obvious candidate)
    llm_lookups: int = 0
    healed: int = 0
    rescued: int = 0            # steps finished by the bounded ReAct fallback
    items_done: int = 0
    items_failed: int = 0

    def line(self) -> str:
        return (f"{self.steps_ok} steps ok, {self.steps_failed} failed, {self.steps_skipped} skipped | "
                f"selector cache hits {self.cache_hits}, local re-finds {self.local_heals}, "
                f"local picks {self.local_picks}, LLM lookups {self.llm_lookups}, healed {self.healed}"
                + (f", rescued {self.rescued}" if self.rescued else ""))


class Executor:
    def __init__(self, session: ChatSession, browser: BrowserSession, llm: LLMRouter, ui: UIBridge,
                 settings: Settings, stop: threading.Event):
        self.session = session
        self.browser = browser
        self.llm = llm
        self.ui = ui
        self.settings = settings
        self.stop = stop
        self.chat_id = session.id
        self.plan = session.plan
        self.task = session.current_task
        self.vars: dict[str, Any] = {}
        self.item: Optional[str] = None
        self.stats = RunStats()
        self.pattern_calls = 0          # shared by every extract_records attempt in this run
        self.run_heals = 0              # LLM heals in this run (all steps and for_each items)
        self.run_rescues = 0            # steps sent to the ReAct fallback in this run
        self.force_visible = False      # set after a captcha in headless mode
        self._resumed = False           # the next attempt follows a user hold (captcha solved)
        self._tok_frames: list[int] = []    # tokens used by nested steps, per open run_step
        self._budget_start = self._tokens()
        self._budget_limit = settings.max_run_tokens
        llm.before_call = self._budget_check
        meta = session.meta
        self.task_type = meta.get("task_type", "others")
        work = meta.get("work_folder", "")
        self.files = FileTools(
            [session.ensure_temp(), session.output_dir, work],
            base=Path(work) if work else session.output_dir,
            extra_files=[meta.get("user_info_file", "")],
            readonly_roots=[session.folder],
        )
        self.user = session.user_info()

    # ------------------------------------------------------------------ helpers
    def log(self, text: str) -> None:
        self.ui.log(text, self.chat_id)

    def check_stop(self) -> None:
        if self.stop.is_set():
            raise StopRequested("stopped by user")

    def save_plan(self) -> None:
        self.session.save_plan(self.plan)
        self.ui.emit("files", self.chat_id)

    def _tokens(self) -> int:
        u = self.session.usage
        return u.get("input_tokens", 0) + u.get("output_tokens", 0)

    def _budget_check(self, purpose: str) -> None:
        """Before every LLM call: past the run's token budget, ask the user (headless: stop)."""
        if not self._budget_limit:
            return
        used = self._tokens() - self._budget_start
        if used < self._budget_limit:
            return
        self.log(f"Token budget reached: {used:,} tokens this run (limit {self._budget_limit:,})")
        if self.ui.confirm(self.chat_id, f"This run has used {used:,} tokens (budget {self._budget_limit:,}).\n\n"
                                         f"Next LLM call: {purpose}. Allow another {self.settings.max_run_tokens:,}?"):
            self._budget_limit += self.settings.max_run_tokens
            return
        raise BudgetExceeded(f"token budget of {self._budget_limit:,} reached ({used:,} used)")

    def rec(self, key: str) -> dict:
        return self.plan.setdefault("execution", {}).setdefault("steps", {}).setdefault(key, {})

    def data(self) -> dict:
        return self.plan.setdefault("data", {})

    def render(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        def rep(m: re.Match) -> str:
            key = m.group(1).strip()
            if key == "item":
                return self.item or ""
            if key.startswith("user."):
                field = key[5:]
                if field not in self.user:
                    got = self.ui.ask_user_info(self.chat_id, [field], f"The task needs '{field}'.")
                    if not got:
                        raise NeedsUser(f"missing user info '{field}'", in_browser=False)
                    self.user.update(got)
                    stored = self.session.user_info()
                    stored.update(got)
                    self.session.save_user_info(stored)
                return str(self.user.get(field, ""))
            v = self.vars.get(key)
            return m.group(0) if v is None else (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))

        return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", rep, value)

    def _ensure_browser(self) -> None:
        meta = self.session.meta
        headless = False if self.force_visible else meta.get("headless")
        self.browser.ensure(profile=meta.get("profile", ""), headless=headless, lang=meta.get("browser_lang"))
        self.browser.extra_wait_ms = 1000 * self._task_wait("page_wait", "page_wait_s")

    def _show_browser(self) -> None:
        """A human cannot solve a captcha in an invisible browser: reopen it visibly on the same page."""
        if self.force_visible or not self.browser.alive or not self.browser.headless:
            return
        if isinstance(self.ui, HeadlessBridge):
            return
        url = self.browser.url
        self.log("Headless mode: opening a visible browser so you can handle this")
        self.force_visible = True
        self._ensure_browser()
        if url.startswith(("http://", "https://")):
            self.browser.goto(url)

    def _after_human(self) -> None:
        """The user pressed Continue: let a redirect started by their captcha answer finish
        before the step runs again (Google: google_abuse cookie -> sgsync -> results)."""
        if not self.browser.alive:
            return
        try:
            self.browser._settle_redirects()
        except Exception:
            pass

    def _task_wait(self, meta_key: str, setting: str) -> int:
        """A wait in seconds: the task's own value (New task dialog) or the Settings default."""
        v = self.session.meta.get(meta_key)
        try:
            return max(0, int(v if v is not None else getattr(self.settings, setting, 0)))
        except (TypeError, ValueError):
            return 0

    def _wait_out_blocker(self, html: Optional[str] = None) -> Optional[str]:
        """Bot check on the page? Many pass by themselves ("Just a moment...", "Checking your
        browser"): re-check for up to the task's bot-check wait before a human is asked.
        Returns the reason if it is still there. Free: no LLM, only page reads."""
        reason = pr.detect_blocker(self.browser.html() if html is None else html)
        wait = self._task_wait("bot_wait", "bot_check_wait_s")
        if not reason or wait <= 0 or not self.browser.alive:
            return reason
        self.log(f"Verification screen ({reason}); waiting up to {wait}s for it to pass by itself")
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            self.check_stop()
            self.browser.page.wait_for_timeout(1000)
            reason = pr.detect_blocker(self.browser.html())
            if not reason:
                self.browser._settle_redirects()
                self.log("Verification passed by itself")
                return None
        return reason

    def _check_blocker(self) -> None:
        reason = self._wait_out_blocker()
        if reason:
            raise NeedsUser(f"Possible captcha/challenge on {self.browser.url} ({reason}). "
                            "Solve it in the browser window, then press Continue.")

    # ------------------------------------------------------------------ run
    def run(self, steps: list[dict], reset_data: bool = False) -> RunStats:
        if reset_data:
            self._reset_data()
        # Every run must produce its own output file; an old one would hide a run that wrote none.
        self.data().pop("output_file", None)
        run_entry = {"started": now_iso(), "status": "running"}
        self.plan.setdefault("runs", []).append(run_entry)
        try:
            for step in steps:
                self.check_stop()
                self.run_step(step)
            run_entry["status"] = "ok" if not self.stats.steps_failed else "partial"
        except StopRequested:
            run_entry["status"] = "stopped"
            raise
        except Exception as e:
            run_entry["status"] = "failed"
            run_entry["error"] = str(e)[:300]
            raise
        finally:
            run_entry.update(finished=now_iso(), stats=asdict(self.stats))
            self.plan["runs"] = self.plan["runs"][-30:]
            self.save_plan()
        return self.stats

    def _reset_data(self) -> None:
        d = self.data()
        for f in d.get("temp_files", []):
            try:
                Path(f["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        d["temp_files"] = []
        d.pop("records_count", None)
        d.pop("output_file", None)      # each run must produce its own (checked after the run)
        if self.task_type != "automation":
            # dedupe = "skip items handled in earlier runs". Automation means it (never apply to the
            # same job twice); for analysis/scraping the items' data was just deleted, so skipping
            # them would leave nothing to analyze.
            d.pop("processed", None)

    def run_step(self, step: dict, prefix: str = "") -> Any:
        start = self._tokens()
        self._tok_frames.append(0)
        try:
            return self._run_step(step, prefix)
        finally:
            self._tok_frames.pop()
            if self._tok_frames:                # tell the parent (for_each) what its children used
                self._tok_frames[-1] += self._tokens() - start

    KEEP_ACTION = ("analyze", "write_output", "extract_records", "for_each")   # heal may fix, not replace

    def _run_step(self, step: dict, prefix: str = "") -> Any:
        key = prefix + str(step.get("id", step.get("step_name", "step")))
        current = step
        heals = user_holds = rescues = 0
        mark = self._tokens()       # heal calls happen between attempts: counted on the next log line
        while True:
            self.check_stop()
            action = current.get("action", "")
            self.ui.emit("status", self.chat_id, text=f"{key}: {current.get('step_name', action)}")
            try:
                try:
                    result = self.dispatch(current, key)
                finally:
                    self._resumed = False       # only the attempt right after a hold may use it
                self.validate(current)
                r = self.rec(key)
                r.update(status="ok", last_ok=now_iso(), error="", runs=r.get("runs", 0) + 1)
                self.stats.steps_ok += 1
                self._log(key, current, "ok", mark)
                self.save_plan()
                return result
            except StopRequested:
                raise
            except LLMError:
                raise
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:400]
                self.rec(key).update(status="failed", error=err, last_fail=now_iso())
                self._log(key, current, "failed", mark, err)
                mark = self._tokens()
                self.log(f"Step {key} failed: {err}")

                if isinstance(e, NeedsUser) and user_holds < 3:
                    user_holds += 1
                    if e.in_browser:
                        try:
                            self._show_browser()
                        except Exception as be:  # noqa: BLE001 - still ask the user
                            self.log(f"Could not open a visible browser: {be}")
                    if self.ui.hold(self.chat_id, str(e)):
                        self._resumed = True
                        self._after_human()
                        continue
                    raise StopRequested("aborted by user")

                can_heal = (heals < self.settings.max_heal_attempts and not isinstance(e, NoHeal))
                if can_heal and self.run_heals >= self.settings.max_heals_per_run:
                    if self.run_heals == self.settings.max_heals_per_run:
                        self.log(f"Heal limit of {self.settings.max_heals_per_run} per run reached; "
                                 "further failures are not sent to the LLM")
                        self.run_heals += 1     # log once
                    can_heal = False
                if can_heal:
                    heals += 1
                    self.run_heals += 1
                    decision = self.heal(current, err)
                    d = (decision or {}).get("decision")
                    if d == "retry" and isinstance(decision.get("step"), dict):
                        new_step = {**current, **decision["step"], "id": current.get("id")}
                        if action in self.KEEP_ACTION and new_step.get("action") != action:
                            # The step that produces the deliverable must stay that step: a heal
                            # that turns "analyze" into "get_page_data" ends "done" with no output.
                            self.log(f"Heal tried to replace '{action}' with '{new_step.get('action')}'; "
                                     f"kept '{action}'")
                            new_step["action"] = action
                        self.log(f"Healing {key}: {new_step.get('step_name', '')}")
                        if (new_step.get("target"), new_step.get("action")) != (current.get("target"), current.get("action")):
                            self._forget(key)   # a different element now; same target keeps its memory
                        self.rec(key)["healed"] = self.rec(key).get("healed", 0) + 1
                        self.stats.healed += 1
                        self._replace_step(new_step)
                        current = new_step
                        continue
                    if d == "skip":
                        self.stats.steps_skipped += 1
                        self.save_plan()
                        return None
                    if d == "ask_user" and self.browser.alive and not self._human_wall()                             and current.get("action") in self.RESCUE_ACTIONS:
                        self.log(f"Heal asked for a human ({str(decision.get('message', ''))[:100]}), but no "
                                 "captcha/login is on the page; trying the page itself first")
                    elif d == "ask_user":
                        if self.ui.hold(self.chat_id, decision.get("message") or err):
                            self._resumed = True
                            self._after_human()
                            continue
                        raise StopRequested("aborted by user")

                # Heal could not fix it: a few guided moves on the live page (bounded ReAct).
                if rescues < 1 and self._can_rescue(current, e):
                    rescues += 1
                    res = self._rescue(current, key, prefix, err)
                    if res == "ok":
                        r = self.rec(key)
                        r.update(status="ok", last_ok=now_iso(), error="", runs=r.get("runs", 0) + 1)
                        self.stats.steps_ok += 1
                        self.stats.rescued += 1
                        self._log(key, current, "ok", mark)
                        self.save_plan()
                        return None
                    if res and res.startswith("user:") and user_holds < 3:
                        user_holds += 1
                        try:
                            self._show_browser()
                        except Exception as be:  # noqa: BLE001 - still ask the user
                            self.log(f"Could not open a visible browser: {be}")
                        if self.ui.hold(self.chat_id, res[5:]):
                            self._resumed = True
                            self._after_human()
                            continue
                        raise StopRequested("aborted by user")

                if current.get("on_fail") == "skip":
                    self.stats.steps_skipped += 1
                    self.save_plan()
                    return None
                self.stats.steps_failed += 1
                self.save_plan()
                raise StepFailed(f"{current.get('step_name', key)}: {err}")

    def _log(self, key: str, step: dict, status: str, since: int, error: str = "") -> None:
        """tokens = this step's own LLM tokens since `since` (nested for_each steps excluded,
        they log their own), so summing steps.json never double counts."""
        children = self._tok_frames[-1] if self._tok_frames else 0
        if self._tok_frames:
            self._tok_frames[-1] = 0
        used = max(0, self._tokens() - since - children)
        self.session.log_step({"step": key, "action": step.get("action"), "name": step.get("step_name", ""),
                               "status": status, "url": self.browser.url, "tokens": used, "error": error,
                               "item": self.item or ""})

    def _replace_step(self, new_step: dict) -> None:
        def walk(steps: list) -> bool:
            for i, s in enumerate(steps):
                if s.get("id") == new_step.get("id"):
                    steps[i] = new_step
                    return True
                if s.get("steps") and walk(s["steps"]):
                    return True
            return False

        if walk(self.task):
            self.session.save_task(self.task)

    # ------------------------------------------------------------------ dispatch
    def dispatch(self, step: dict, key: str) -> Any:
        action = step.get("action", "")
        tool = toolbox.REGISTRY.get(action)
        if tool is None:
            # A heal or patch may still name a tool wrongly ("Browser", "open url"): fix it for free
            # before paying for another heal.
            guess = toolbox.guess(step, self.task_type)
            if not guess:
                raise StepFailed(f"unknown tool '{action}'")
            self.log(f"{key}: action '{action}' is not a tool; using '{guess}' (no LLM)")
            step["action"] = action = guess
            self._replace_step(step)
            tool = toolbox.REGISTRY[guess]
        if not toolbox.allowed(action, self.task_type):
            raise StepFailed(f"tool '{action}' is not available for {self.task_type} tasks")
        if tool.browser:
            self._ensure_browser()
        return getattr(self, f"act_{action}")(step, key)

    # ---- browser tools
    CHALLENGE_STATUS = (403, 429)   # bot walls answer with these; not a wrong address

    def act_open_url(self, step: dict, key: str) -> None:
        url = self.render(step.get("url", ""))
        fb = self.render(step.get("fallback_url", ""))
        if self._resumed and self.browser.same_page(url) and not pr.detect_blocker(self.browser.html()):
            # The user just solved a captcha and the site already brought them to this page.
            # Loading it again would hit the bot check again (and races the site's redirect).
            self.log(f"{key}: already on the page after your help; not reloading it")
            self._check_session(url)
            return
        try:
            status = self.browser.goto(url)
        except Exception:
            if not fb:
                raise
            self.log(f"{url} failed, trying fallback {fb}")
            status, fb = self.browser.goto(fb), ""
        if status in self.CHALLENGE_STATUS:
            # Google Scholar & co. answer 429/403 with a captcha page. Healing (LLM) or searching
            # the site root would only add requests and deepen the block: hand it to the human.
            # Cloudflare's automatic check is also a 403 and passes by itself: wait for it first.
            html = self.browser.html()
            if pr.detect_blocker(html) and not self._wait_out_blocker(html):
                status = 200            # the check passed; we are on the real page now
            else:
                reason = pr.detect_blocker(self.browser.html()) or f"HTTP {status}, the site is blocking automated visits"
                raise NeedsUser(f"Possible captcha/challenge on {pr.short_url(self.browser.url)} ({reason}). "
                                "Solve it in the browser window (or wait a minute), then press Continue.")
        if status >= 400 and fb:
            self.log(f"{url} returned HTTP {status}, trying fallback {fb}")
            status = self.browser.goto(fb)
        if status >= 400:
            # Planners guess deep URLs ("books-travel_2" for "books/travel_2"). An error page would
            # only waste lookups/pattern calls: find the real page by its link on the site, free.
            found = "" if "{{" in str(step.get("url", "")) else self._find_by_link(url, step)
            if not found:
                raise StepFailed(f"HTTP {status} for {url} (the address may be wrong)")
            self.log(f"{key}: {url} returned HTTP {status}; found the page by its link instead: {found} (no LLM)")
            step["url"] = found
            self._replace_step(dict(step))
            url = found
        self._check_blocker()
        self._check_session(url)

    URL_NOISE = {"index", "html", "htm", "php", "aspx", "catalogue", "catalog", "category", "www", "open", "page"}

    def _find_by_link(self, url: str, step: dict) -> str:
        """The site's own link that best matches a URL that returned an error: path similarity
        plus words of the path and step name in the link text. Only a clear winner is used."""
        from urllib.parse import urlparse
        u = urlparse(url if "://" in url else "https://" + url)
        if not u.netloc:
            return ""
        try:
            if self.browser.goto(f"{u.scheme}://{u.netloc}/") >= 400:
                return ""
        except Exception:
            return ""
        links = [l for l in pr.links(self.browser.html(), self.browser.url) if urlparse(l["href"]).netloc == u.netloc]
        words = set(pr.hint_words(f"{u.path} {step.get('step_name', '')}")) - self.URL_NOISE
        want = u.path.lower()

        def score(l: dict) -> float:
            path = urlparse(l["href"]).path.lower()
            return (difflib.SequenceMatcher(None, want, path).ratio()
                    + 0.3 * len(words & set(pr.hint_words(f"{l['text']} {path}"))))
        ranked = sorted(((score(l), l["href"]) for l in links), reverse=True)
        if not ranked or ranked[0][0] < 0.6 or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.05):
            return ""
        try:
            return ranked[0][1] if self.browser.goto(ranked[0][1]) < 400 else ""
        except Exception:
            return ""

    def _check_session(self, requested: str) -> None:
        """Login tasks: opening a page but landing on a login form means the saved session
        expired. Stop clearly instead of letting element lookups and heals burn tokens on a
        login page (scheduled runs hit this when cookies run out)."""
        if not (self.plan.get("requirements") or {}).get("needs_login"):
            return
        from urllib.parse import urlparse
        want, got = urlparse(requested if "://" in requested else "https://" + requested), urlparse(self.browser.url)
        if (want.netloc, want.path.rstrip("/")) == (got.netloc, got.path.rstrip("/")):
            return                  # this IS the page that was asked for (e.g. the login page itself)
        if pr.detect_login_wall(self.browser.html(), self.browser.url):
            raise NeedsUser(f"The site asks you to log in again ({pr.short_url(self.browser.url)}): the saved "
                            "session has expired. Log in in the browser window, then press Continue - the "
                            "profile keeps the new cookies for the next runs.")

    def act_fill(self, step: dict, key: str) -> None:
        self.browser.fill(self.resolve(step, key), self.render(step.get("value", "")))

    def act_click(self, step: dict, key: str) -> None:
        self.browser.click(self.resolve(step, key))
        self._check_blocker()

    def act_press(self, step: dict, key: str) -> None:
        sel = self.resolve(step, key) if step.get("target") else ""
        self.browser.press(step.get("key", "Enter"), sel)
        self._check_blocker()

    def act_select_option(self, step: dict, key: str) -> None:
        self.browser.select(self.resolve(step, key), self.render(step.get("value", "")))

    def act_scroll(self, step: dict, key: str) -> None:
        self.browser.scroll(int(step.get("times", 1)))

    def act_wait(self, step: dict, key: str) -> None:
        if step.get("target"):
            self.browser.wait_for(self.resolve(step, key))
        else:
            self.browser.page.wait_for_timeout(float(step.get("seconds", 2)) * 1000)

    def act_screenshot(self, step: dict, key: str) -> str:
        folder = self.session.ensure_temp() / "screens"
        folder.mkdir(exist_ok=True)
        path = folder / f"{re.sub(r'[^A-Za-z0-9]+', '_', step.get('label', key))}.png"
        self.browser.screenshot(path)
        return str(path)

    def act_download(self, step: dict, key: str) -> str:
        path = self.browser.download(self.resolve(step, key), self.session.output_dir)
        if step.get("save_as"):
            self.vars[step["save_as"]] = str(path)
        self.log(f"Downloaded: {path}")
        return str(path)

    def act_upload(self, step: dict, key: str) -> None:
        path = self.files.path(self.render(step.get("value", "")), must_exist=True)
        self.browser.upload(self.resolve(step, key), str(path))

    def act_save_session(self, step: dict, key: str) -> None:
        path = self.session.folder / "session_state.json"
        self.browser.save_storage(path)
        self.plan.setdefault("requirements", {})["session_file"] = str(path)

    # ---- page data tools
    def act_get_page_data(self, step: dict, key: str) -> str:
        title, text = pr.main_text(self.browser.html(), self.settings.max_page_chars)
        return self._add_data(title, self.browser.url, text, self.render(step.get("label", "")))

    def act_extract_records(self, step: dict, key: str) -> int:
        from .scraping import ScrapeEngine
        return ScrapeEngine(self).run(step, key)

    # ---- flow tools
    def act_ask_user(self, step: dict, key: str) -> None:
        if not self.ui.hold(self.chat_id, self.render(step.get("message", "Please check the browser."))):
            raise StopRequested("aborted by user")

    # ---- built-in local file tools
    def act_list_files(self, step: dict, key: str) -> list[str]:
        items = self.files.list(self.render(step.get("path", ".")), self.render(step.get("pattern", "*")),
                                bool(step.get("recursive")))
        self.vars[step.get("save_as", "files")] = items
        self.log(f"Found {len(items)} files")
        return items

    def act_read_file(self, step: dict, key: str) -> str:
        path = self.render(step.get("path", ""))
        content = self.files.read(path)
        if step.get("save_as"):
            self.vars[step["save_as"]] = content
        if step.get("as_data"):
            p = self.files.path(path)
            self._add_data(p.name, str(p), content[: self.settings.max_page_chars], self.render(step.get("label", "")))
        return content

    def act_write_file(self, step: dict, key: str) -> str:
        return str(self.files.write(self.render(step.get("path", "output.txt")), self.render(step.get("value", ""))))

    def act_append_file(self, step: dict, key: str) -> str:
        return str(self.files.write(self.render(step.get("path", "output.txt")), self.render(step.get("value", "")),
                                    append=True))

    def act_copy_file(self, step: dict, key: str) -> str:
        return str(self.files.copy(self.render(step.get("path", "")), self.render(step.get("dest", ""))))

    def act_move_file(self, step: dict, key: str) -> str:
        return str(self.files.move(self.render(step.get("path", "")), self.render(step.get("dest", ""))))

    def act_delete_file(self, step: dict, key: str) -> str:
        return str(self.files.delete(self.render(step.get("path", ""))))

    def act_make_dir(self, step: dict, key: str) -> str:
        return str(self.files.make_dir(self.render(step.get("path", ""))))

    def act_file_exists(self, step: dict, key: str) -> bool:
        ok = self.files.exists(self.render(step.get("path", "")))
        self.vars[step.get("save_as", "exists")] = "true" if ok else "false"
        return ok

    # ---- result tools
    def act_analyze(self, step: dict, key: str) -> str:
        from .analysis import AnalysisEngine
        path = AnalysisEngine(self).run(self.render(step.get("instructions", "")))
        self.vars["output_file"] = str(path)
        return str(path)

    def act_write_output(self, step: dict, key: str) -> str:
        return self.write_output()

    def validate(self, step: dict) -> None:
        v = step.get("validation") or {}
        if not v or not self.browser.alive:
            return
        if v.get("url_contains") and v["url_contains"].lower() not in self.browser.url.lower():
            raise StepFailed(f"validation: url does not contain '{v['url_contains']}'")
        if v.get("text_contains"):
            # Whole page incl. header/nav: a search box value or heading there is a valid match.
            text = " ".join(pr.soup_of(self.browser.html()).get_text(" ").split()).lower()
            title = self.browser.title().lower()
            if v["text_contains"].lower() not in text and v["text_contains"].lower() not in title:
                raise StepFailed(f"validation: page does not contain '{v['text_contains']}'")

    # ------------------------------------------------------------------ element resolution
    # Attributes that identify an element across page loads (text and value may be live data).
    STABLE_ATTRS = ("id", "name", "type", "placeholder", "aria-label", "data-testid", "role", "alt")
    MEMORY_FIELDS = ("selector", "alternates", "element", "fingerprint", "dynamic_text", "page")

    def _mem_key(self, key: str, raw_target: str, target: str) -> str:
        """Element memory key. A templated target ("result titled {{item}}") is a different
        element per value, so each rendered target gets its own memory."""
        if raw_target and target != raw_target:
            return f"{key}@{hashlib.sha1(target.encode('utf-8', 'replace')).hexdigest()[:10]}"
        return key

    def _forget(self, key: str) -> None:
        r = self.rec(key)
        for k in self.MEMORY_FIELDS:
            r.pop(k, None)

    @classmethod
    def _stable(cls, attrs: dict) -> dict:
        out = {}
        for k in cls.STABLE_ATTRS:
            v = (attrs or {}).get(k)
            if not v:
                continue
            if k == "id" and (re.search(r"\d{3,}|:", v) or pr._HASHED_CLASS.search(v)):
                continue            # generated ids (":r1:", "ember123") change between loads
            out[k] = v
        return out

    def _identity(self, mem: dict, now: dict) -> tuple[bool, bool]:
        """(same element?, text changed while the attributes match - i.e. the text is live data).
        Old memories without an element identity fall back to the text fingerprint."""
        stored = mem.get("element")
        if not stored:
            fp, cur = mem.get("fingerprint", ""), (now or {}).get("text", "")
            if not fp and not cur:
                return True, False
            return bool(fp and cur and self._same(fp, cur)), False
        if not now or now.get("tag") != stored.get("tag"):
            return False, False
        want, have = self._stable(stored.get("attrs", {})), (now.get("attrs") or {})
        attrs_ok = all(have.get(k) == v for k, v in want.items())
        st, cur = stored.get("text", ""), now.get("text", "")
        if mem.get("dynamic_text"):
            text_ok = True
        elif st or cur:
            text_ok = bool(st and cur and self._same(st, cur))
        else:
            text_ok = True
        if want:
            return attrs_ok, attrs_ok and not text_ok
        return text_ok, False

    def _match_score(self, stored: dict, cand: dict) -> float:
        """How well a candidate matches a remembered element (for a local re-find)."""
        if cand.get("tag") != stored.get("tag"):
            return 0.0
        want, have = self._stable(stored.get("attrs", {})), self._stable(cand.get("attrs", {}))
        score = 1.0 + sum(3.0 for k, v in want.items() if have.get(k) == v)
        st, ct = (stored.get("text") or "").lower(), (cand.get("text") or "").lower()
        if st and ct:
            score += 4.0 * difflib.SequenceMatcher(None, st, ct).ratio()
        if stored.get("attrs", {}).get("href") and stored["attrs"]["href"] == cand.get("attrs", {}).get("href"):
            score += 2.0
        return score

    def _try_cached(self, mem: dict, key: str) -> Optional[str]:
        """Cached selector, then stored alternates; each verified against the element identity."""
        tried = [mem.get("selector")] + list(mem.get("alternates") or [])
        for n, sel in enumerate(s for s in tried if s):
            if not self.browser.exists(sel):
                continue
            ok, live_text = self._identity(mem, self.browser.describe(sel))
            if not ok:
                continue
            if live_text:
                mem["dynamic_text"] = True
                self.log(f"{key}: element text changes between runs; matching it by attributes from now on")
            if n:
                self.log(f"{key}: cached selector broke, re-found with a stored alternate locator (no LLM)")
                self.stats.local_heals += 1
                self._remember(mem, sel)
            else:
                self.stats.cache_hits += 1
            return sel
        return None

    def _visible(self, cands: list[dict], limit: Optional[int] = None) -> list[dict]:
        """Drop candidates the user cannot see (hidden parent, CSS class, closed menu) - one
        browser call - so neither the local picker nor the LLM spends a lookup on them.
        Re-numbers "i" to match list positions (PICK answers are list indices)."""
        if cands:
            flags = self.browser.visible_many([c["selector"] for c in cands])
            cands = [c for c, ok in zip(cands, flags) if ok]
        cands = cands[:limit] if limit else cands
        for i, c in enumerate(cands):
            c["i"] = i
        return cands

    def _local_refind(self, mem: dict, html: str, action: str, target: str) -> Optional[str]:
        """The remembered element moved or its selector changed: find it again among the page's
        elements by tag, stable attributes and text - only when one candidate clearly wins."""
        stored = mem.get("element")
        if not stored:
            return None
        cands = self._visible(pr.candidates(html, action, target, level=2, limit=80))
        scored = sorted(((self._match_score(stored, c), c) for c in cands), key=lambda t: -t[0])
        if not scored:
            return None
        best, cand = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        strong = best >= 4.0 and best - second >= 1.5
        if not strong or not self.browser.exists(cand["selector"]):
            return None
        ok, _ = self._identity({**mem, "dynamic_text": True}, self.browser.describe(cand["selector"]))
        return cand["selector"] if ok or not self._stable(stored.get("attrs", {})) else None

    def resolve(self, step: dict, key: str) -> str:
        raw_target = step.get("target", "") or ""
        target = self.render(raw_target) or step.get("step_name", "")
        action = step.get("action", "click")
        mem = self.rec(self._mem_key(key, raw_target, target))

        sel = self._try_cached(mem, key)
        if sel:
            return sel
        had_memory = bool(mem.get("selector"))

        html = self.browser.html()
        reason = pr.detect_blocker(html) and self._wait_out_blocker(html)
        if reason:
            raise NeedsUser(f"Possible captcha/challenge ({reason}). Solve it in the browser, then Continue.")
        if pr.detect_blocker(html):
            html = self.browser.html()      # the check passed: read the real page

        if had_memory:
            sel = self._local_refind(mem, html, action, target)
            if sel:
                self.log(f"{key}: element changed on the page; re-found it locally (no LLM)")
                self.stats.local_heals += 1
                return self._remember(mem, sel)
            self.log(f"{key}: cached element is gone; looking it up again")

        info = {k: step.get(k) for k in ("step_name", "action", "target", "value") if step.get(k)}
        if target != raw_target:
            info["resolved_target"] = target
        brief = json.dumps(info, ensure_ascii=False)
        url = self.browser.url
        page = f"Page: {pr.short_url(url)} | {self.browser.title()}"

        for level in (1, 2):
            want = 15 if level == 1 else 60
            cands = self._visible(pr.candidates(html, action, target, level, limit=want * 2), want)
            if not cands:
                continue
            if level == 1:
                pick = pr.obvious_choice(cands, action)
                if pick and self.browser.exists(pick["selector"]):
                    self.stats.local_picks += 1
                    self.log(f"{key}: picked '{pick['text'] or pick['tag']}' without the LLM (clear match)")
                    return self._remember(mem, pick["selector"])
            if step.get("optional"):
                continue                # learned prep step (popup, menu): never worth an LLM call
            self.stats.llm_lookups += 1
            ans = self.llm.ask_json("pick", prompts.PICK,
                                    f"Step: {brief}\n{page}\nCandidates:\n{pr.candidates_for_prompt(cands, url)}",
                                    max_tokens=150)
            ans = ans if isinstance(ans, dict) else {}
            if ans.get("need") == "user":
                self._model_says_user(ans.get("reason"))
            try:
                idx = int(ans.get("index", -1))
            except (TypeError, ValueError):
                idx = -1
            if 0 <= idx < len(cands) and self.browser.exists(cands[idx]["selector"]):
                return self._remember(mem, cands[idx]["selector"])

        if step.get("optional"):
            raise NoHeal(f"optional element not on the page: {target}")
        # Outline: first only the parts that mention the target (about a quarter of the tokens),
        # then the full outline if that did not give a working selector.
        outline = pr.page_outline(html, self.settings.max_page_chars)
        focused = pr.focus_outline(outline, target, max_chars=min(3000, self.settings.max_page_chars // 3))
        for view, label in ((focused, "focused"), (outline, "full")):
            if not view:
                continue
            self.stats.llm_lookups += 1
            ans = self.llm.ask_json("locate", prompts.LOCATE, f"Step: {brief}\n{page}\nOutline:\n{view}",
                                    max_tokens=200)
            ans = ans if isinstance(ans, dict) else {}
            sel = ans.get("selector")
            if sel and self.browser.exists(sel):
                if label == "focused":
                    self.log(f"{key}: found from the focused outline ({len(view):,} of {len(outline):,} chars)")
                return self._remember(mem, sel)
            if ans.get("need") == "user" and label == "full":   # the focused view may just lack context
                self._model_says_user(ans.get("reason"))
        raise StepFailed(f"element not found: {target}")

    def _human_wall(self) -> bool:
        html = self.browser.html()
        return bool(pr.detect_blocker(html) or pr.detect_login_wall(html, self.browser.url))

    def _model_says_user(self, reason: Optional[str]) -> None:
        """The model claims a human is needed. Trust it only when a captcha / login form is really
        on the page; small models also say it for hidden or not-yet-loaded elements, which heal
        and the ReAct fallback can handle without stopping the run."""
        reason = reason or "The agent needs your help in the browser."
        if self._human_wall():
            raise NeedsUser(reason)
        self.log(f"Model asked for a human ({reason[:120]}), but no captcha/login is on the page; "
                 "treating the element as not found")

    def _remember(self, mem: dict, selector: str) -> str:
        """Store the selector with the element's identity and a few alternate locators."""
        desc = self.browser.describe(selector) or {"tag": "", "text": self.browser.element_text(selector)[:80], "attrs": {}}
        mem["selector"] = selector
        mem["element"] = desc
        mem["fingerprint"] = (desc.get("text") or "")[:60]
        mem["alternates"] = self._alternates(desc, selector)
        mem["page"] = self.browser.url.split("?")[0]
        mem.pop("dynamic_text", None)
        return selector

    def _alternates(self, desc: dict, primary: str) -> list[str]:
        """Other ways to find the same element (each must match exactly one element now)."""
        tag = desc.get("tag") or "*"
        attrs = self._stable(desc.get("attrs", {}))
        options = []
        if attrs.get("id") and pr._SAFE_ID.match(attrs["id"]):
            options.append(f"#{attrs['id']}")
        for k in ("data-testid", "name", "aria-label", "placeholder"):
            if attrs.get(k):
                options.append(f'{tag}[{k}="{pr._q(attrs[k])}"]')
        text = desc.get("text") or ""
        if text and len(text) <= 40 and tag in ("a", "button", "label", "summary", "option", "li", "span"):
            options.append(f'{tag}:text-is("{pr._q(text)}")')
        out = []
        for sel in options:
            if sel == primary or sel in out:
                continue
            try:
                if self.browser.page.locator(sel).count() == 1:
                    out.append(sel)
            except Exception:
                continue
            if len(out) >= 3:
                break
        return out

    @staticmethod
    def _same(a: str, b: str) -> bool:
        a, b = (a or "").strip().lower(), (b or "").strip().lower()
        if not a or not b:
            return a == b
        return a[:30] in b or b[:30] in a or difflib.SequenceMatcher(None, a, b).ratio() > 0.6

    # ------------------------------------------------------------------ healing
    def heal(self, step: dict, error: str) -> Optional[dict]:
        cands = ""
        page = "no page open"
        if self.browser.alive:
            try:
                html = self.browser.html()
                url = self.browser.url
                cands = pr.candidates_for_prompt(self._visible(pr.candidates(
                    html, step.get("action", "click"), self.render(step.get("target", "")), 2, limit=50), 25), url)
                page = f"{pr.short_url(url)} | {self.browser.title()}"
            except Exception:
                pass
        # Only the fields a heal can change: no cached memory, no long values.
        brief = {k: (v[:300] if isinstance(v, str) else v) for k, v in step.items() if k != "steps"}
        try:
            ans = self.llm.ask_json(
                "heal", prompts.heal_system(self.task_type),
                f"Goal: {self.plan.get('goal', '')[:300]}\nFailed step: {json.dumps(brief, ensure_ascii=False)}\n"
                f"Error: {error[:300]}\nCurrent page: {page}\nVisible elements:\n{cands}",
                max_tokens=600)
            return ans if isinstance(ans, dict) else None
        except BudgetExceeded:
            raise
        except (LLMError, ValueError) as e:
            self.log(f"Healing unavailable: {e}")
            return None

    # ------------------------------------------------------------------ bounded ReAct fallback
    RESCUE_ACTIONS = ("click", "fill", "press", "select_option", "wait")
    MOVES = ("click", "fill", "press", "select_option", "scroll", "wait")

    def _can_rescue(self, step: dict, e: Exception) -> bool:
        return (self.settings.max_rescue_turns > 0 and self.run_rescues < self.settings.max_rescues_per_run
                and step.get("action") in self.RESCUE_ACTIONS and step.get("on_fail") != "skip"
                and not step.get("optional") and not isinstance(e, (NoHeal, NeedsUser)) and self.browser.alive)

    def _rescue(self, step: dict, key: str, prefix: str, err: str) -> Optional[str]:
        """A few observe -> act turns on the live page for ONE step that heal could not fix.
        Each turn sends only the step, the moves so far and ~30 element lines (never the page or a
        growing transcript). Returns "ok", "user:<reason>" or None (gave up).
        When the final move is the step's own action, its element is remembered and the moves
        before it (popup closed, form revealed, ...) are saved as optional prep steps, so the
        next run replays everything without the LLM."""
        self.run_rescues += 1
        turns = self.settings.max_rescue_turns
        raw_target = step.get("target", "") or ""
        target = self.render(raw_target) or step.get("step_name", "")
        info = {k: step.get(k) for k in ("step_name", "action", "target", "value", "key") if step.get(k)}
        if target != raw_target:
            info["resolved_target"] = target
        brief = json.dumps(info, ensure_ascii=False)
        mem_key = self._mem_key(key, raw_target, target)
        history: list[str] = []
        learned: list[dict] = []
        self.log(f"{key}: heal could not fix the step; trying up to {turns} guided moves (ReAct fallback)")
        for _ in range(turns):
            self.check_stop()
            html = self.browser.html()
            reason = pr.detect_blocker(html) and self._wait_out_blocker(html)
            if pr.detect_blocker(html) and not reason:
                html = self.browser.html()
            if reason:
                return f"user:Possible captcha/challenge ({reason}). Solve it in the browser, then Continue."
            cands = self._visible(pr.candidates(html, step.get("action", "click"),
                                                f"{target} {step.get('step_name', '')}", 2, limit=60), 30)
            url = self.browser.url
            user = (f"Goal: {self.plan.get('goal', '')[:200]}\nStep: {brief}\nError: {err[:200]}\n"
                    f"Moves so far: {'; '.join(history) or 'none'}\n"
                    f"Page: {pr.short_url(url)} | {self.browser.title()}\n"
                    f"Elements:\n{pr.candidates_for_prompt(cands, url)}")
            try:
                ans = self.llm.ask_json("rescue", prompts.RESCUE, user, max_tokens=150)
            except BudgetExceeded:
                raise
            except (LLMError, ValueError) as e:
                self.log(f"ReAct fallback unavailable: {e}")
                return None
            ans = ans if isinstance(ans, dict) else {}
            do = ans.get("do")
            if do == "user":
                if self._human_wall():
                    return "user:" + (ans.get("reason") or "The agent needs your help in the browser.")
                history.append(f"asked for a human ({str(ans.get('reason', ''))[:60]}) but no captcha/login is "
                               "visible -> act on the page instead")
                continue
            if do not in self.MOVES:
                self.log(f"{key}: ReAct fallback gave up: {str(ans.get('reason', ''))[:200]}")
                return None
            final = bool(ans.get("final"))
            same = final and do == step.get("action")
            sel, move_mem, label = "", {}, do
            if do in ("click", "fill", "select_option") or (do == "press" and "index" in ans):
                try:
                    idx = int(ans.get("index", -1))
                except (TypeError, ValueError):
                    idx = -1
                if not (0 <= idx < len(cands)) or not self.browser.exists(cands[idx]["selector"]):
                    history.append(f"{do} [{ans.get('index')}] -> no such visible element")
                    continue
                sel = cands[idx]["selector"]
                self._remember(move_mem, sel)       # identity + alternates while the element is there
                el = move_mem.get("element") or {}
                label = f"{do} '{(el.get('text') or el.get('attrs', {}).get('placeholder') or el.get('tag') or sel)[:40]}'"
            # The step's own value (may be user info) is used for the step's own action; the LLM's
            # value only for helper moves.
            value = self.render(step.get("value", "")) if same else str(ans.get("value", ""))
            press_key = str(ans.get("key") or step.get("key") or "Enter")
            try:
                self._do_move(do, sel, value, press_key)
                if final:
                    self.validate(step)
            except StopRequested:
                raise
            except NeedsUser as ne:
                return f"user:{ne}"
            except Exception as me:  # noqa: BLE001 - tell the model and let it try another move
                history.append(f"{label} -> failed: {str(me)[:100]}")
                continue
            if final:
                if same and sel:
                    mem = self.rec(mem_key)
                    for k in self.MEMORY_FIELDS:
                        mem.pop(k, None)
                    mem.update({k: v for k, v in move_mem.items() if k in self.MEMORY_FIELDS})
                    self._learn(step, prefix, learned)
                    self.log(f"{key}: done by the ReAct fallback in {len(history) + 1} moves; "
                             f"saved for the next run ({len(learned)} prep steps)")
                else:
                    self.log(f"{key}: done by the ReAct fallback with a different move ({label}); "
                             "not saved, the next run heals again if needed")
                return "ok"
            history.append(f"{label} -> ok, page now {pr.short_url(self.browser.url)}")
            if sel:
                learned.append({"action": do, "mem": move_mem, "label": label, "value": value, "key": press_key})
        self.log(f"{key}: ReAct fallback used its {turns} moves without finishing the step")
        return None

    def _do_move(self, do: str, sel: str, value: str, key: str) -> None:
        b = self.browser
        if do == "click":
            b.click(sel)
            self._check_blocker()
        elif do == "fill":
            b.fill(sel, value)
        elif do == "press":
            b.press(key, sel)
            self._check_blocker()
        elif do == "select_option":
            b.select(sel, value)
        elif do == "scroll":
            b.scroll(1)
        elif do == "wait":
            b.page.wait_for_timeout(1500)

    def _learn(self, step: dict, prefix: str, learned: list[dict]) -> None:
        """Insert the helper moves before the step as optional prep steps with their elements
        remembered. Optional = when the element is not there next time (no popup today), the
        step is skipped without any LLM call."""
        if not learned:
            return
        used: set = set()

        def ids(items: list) -> None:
            for s in items:
                used.add(str(s.get("id")))
                ids(s.get("steps") or [])
        ids(self.task)
        new_steps = []
        for i, mv in enumerate(learned, 1):
            sid = f"{step.get('id')}_r{i}"
            while sid in used:
                sid += "_"
            used.add(sid)
            el = mv["mem"].get("element") or {}
            st = {"id": sid, "step_name": f"prep: {mv['label']}"[:40], "action": mv["action"],
                  "target": (el.get("text") or el.get("attrs", {}).get("placeholder") or mv["label"])[:80],
                  "on_fail": "skip", "optional": True}
            if mv["action"] in ("fill", "select_option"):
                st["value"] = mv["value"]
            if mv["action"] == "press":
                st["key"] = mv["key"]
            rec = self.rec(prefix + sid)
            rec.clear()
            rec.update({k: v for k, v in mv["mem"].items() if k in self.MEMORY_FIELDS})
            new_steps.append(st)

        def insert(items: list) -> bool:
            for i, s in enumerate(items):
                if s.get("id") == step.get("id"):
                    items[i:i] = new_steps
                    return True
                if s.get("steps") and insert(s["steps"]):
                    return True
            return False
        if insert(self.task):
            self.session.save_task(self.task)

    # ------------------------------------------------------------------ data actions
    def _add_data(self, title: str, source: str, text: str, label: str = "") -> str:
        """Save collected text as a data file in the temp folder (input for analyze)."""
        files = self.data().setdefault("temp_files", [])
        existing = next((f for f in files if f.get("url") == source), None)
        path = Path(existing["path"]) if existing else self.session.ensure_temp() / f"data_{len(files) + 1:03d}.md"
        path.write_text(f"# {title}\nSource: {source}\nLabel: {label}\n\n{text}", encoding="utf-8")
        if not existing:
            files.append({"path": str(path), "url": source, "title": title, "chars": len(text), "label": label})
        self.log(f"Saved data ({len(text)} chars): {title[:60]}")
        return str(path)

    def act_collect_links(self, step: dict, key: str) -> list[str]:
        all_links = pr.links(self.browser.html(), self.browser.url)
        limit = int(step.get("limit") or 10)
        r = self.rec(key)
        chosen = []
        sigs = set(r.get("link_signatures", []))
        hrefs = set(r.get("link_hrefs", []))
        if sigs or hrefs:
            # Same link shape (new results on a results page) or the very same link (stable pages,
            # e.g. links inside an article, whose shapes are too generic to store).
            chosen = [l for l in all_links if l["sig"] in sigs or l["href"] in hrefs][:limit]
            # Far fewer links than last time = the shapes only partly match the page now (layout
            # change): ask again rather than silently collect less. Equal or close: free reuse.
            before = int(r.get("link_count") or 0)
            if chosen and len(chosen) * 2 < min(before, limit):
                self.log(f"Only {len(chosen)} of the {before} remembered result links match now; picking again")
                chosen = []
            if chosen:
                self.stats.cache_hits += 1
        if not chosen:
            shown = pr.links_to_offer(all_links, self.render(step.get("target", "")), limit)
            if len(shown) < len(all_links):
                self.log(f"Links offered to the LLM: {len(shown)} of {len(all_links)} (repeated / menu links left out)")
            listing = pr.links_for_prompt(shown, self.browser.url)
            self.stats.llm_lookups += 1
            ans = self.llm.ask_json("pick", prompts.PICK_LINKS,
                                    f"Want: {self.render(step.get('target', ''))} (limit {limit})\n"
                                    f"Page: {pr.short_url(self.browser.url)}\nLinks:\n{listing}", max_tokens=300)
            idxs = ans.get("indices", []) if isinstance(ans, dict) else ans if isinstance(ans, list) else []
            chosen = [shown[int(i)] for i in idxs if str(i).lstrip("-").isdigit() and 0 <= int(i) < len(shown)][:limit]
            if not chosen:
                chosen = pr.result_group(shown)[:limit]
                if chosen:
                    self.log(f"LLM picked no link; using the page's repeated result links ({len(chosen)}) (no LLM)")
            # Remember link "shapes" only when they are specific enough to reuse.
            good = set()
            for l in chosen:
                same = sum(1 for x in all_links if x["sig"] == l["sig"])
                if "." in l["sig"] and same <= max(limit * 3, 30):
                    good.add(l["sig"])
            r["link_signatures"] = sorted(good)
            r["link_hrefs"] = [l["href"] for l in chosen]
            r["link_count"] = len(chosen)
        urls = [l["href"] for l in chosen]
        self.vars[step.get("save_as", "links")] = urls
        self.data().setdefault("collected", {})[step.get("save_as", "links")] = urls
        self.log(f"Collected {len(urls)} links")
        if not urls:
            raise StepFailed("no matching links found")
        return urls

    LOOP_FAIL_FAST = 3      # consecutive failed items at the start of a loop = broken loop

    def act_for_each(self, step: dict, key: str) -> int:
        source = step.get("source", "links")
        items = self.vars.get(source)
        if items is None:
            items = self.data().get("collected", {}).get(source, [])
        if isinstance(items, str):
            items = [items]
        limit = int(step.get("limit") or len(items) or 0)
        dedupe = bool(step.get("dedupe"))
        processed = self.data().setdefault("processed", {}).setdefault(key, []) if dedupe else []
        done = failed = 0
        last_error = ""
        for item in items:
            if done >= limit:
                break
            if dedupe and item in processed:
                continue
            self.check_stop()
            self.item = str(item)
            try:
                for sub in step.get("steps", []):
                    self.run_step(sub, prefix=key + ".")
                done += 1
                self.stats.items_done += 1
                if dedupe:
                    processed.append(item)
                    self.save_plan()
            except StopRequested:
                raise
            except LLMError:
                raise
            except Exception as e:
                failed += 1
                last_error = str(e)[:200]
                self.stats.items_failed += 1
                self.log(f"Item failed ({item}): {e}")
                if not done and failed >= self.LOOP_FAIL_FAST:
                    self.item = None
                    # The first items all fail: the loop itself is broken. Stop before every
                    # remaining item pays for the same heals and timeouts.
                    raise NoHeal(f"the first {failed} items all failed; stopped the loop. Last error: {last_error}")
            finally:
                self.item = None
        self.log(f"for_each {key}: {done} items processed" + (f", {failed} failed" if failed else ""))
        if failed and not done:
            # Every item failed: the loop is broken, not one bad item. Report it as a failed step
            # (no step heal: the inner steps were already healed per item).
            raise NoHeal(f"all {failed} items failed; last error: {last_error}")
        return done

    def write_output(self) -> str:
        from . import output
        out = self.plan.get("output", {})
        fmt = output.normalize_format(out.get("format", "csv"))
        path = output.output_path(self.session.output_dir, out.get("filename", "output"), fmt)
        records = self.vars.get("records")
        if records is None and self.data().get("records_file"):
            records = json.loads(Path(self.data()["records_file"]).read_text(encoding="utf-8"))
        if records is None:
            # Automation: write the log of handled items (for_each with dedupe).
            records = [{"loop": loop, "item": item}
                       for loop, items in self.data().get("processed", {}).items() for item in items]
        scraped = self.vars.get("records") is not None or bool(self.data().get("records_file"))
        if not records and not scraped:
            raise StepFailed("nothing to write: no records or processed items yet")
        # A scrape where nothing matched the filters is a valid answer: write the header only.
        cols = [f.get("name") for f in (self.plan.get("scrape") or {}).get("fields", []) if isinstance(f, dict)]
        final = output.write_rows(records, path, columns=[c for c in cols if c])
        if not records:
            self.log("No records matched; wrote a file with the header only")
        self.data()["output_file"] = str(final)
        self.log(f"Output written: {final}")
        return str(final)


_missing = [name for name in toolbox.REGISTRY if not hasattr(Executor, f"act_{name}")]
assert not _missing, f"tools without an Executor.act_<name> handler: {_missing}"
