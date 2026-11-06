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
    items_done: int = 0
    items_failed: int = 0

    def line(self) -> str:
        return (f"{self.steps_ok} steps ok, {self.steps_failed} failed, {self.steps_skipped} skipped | "
                f"selector cache hits {self.cache_hits}, local re-finds {self.local_heals}, "
                f"local picks {self.local_picks}, LLM lookups {self.llm_lookups}, healed {self.healed}")


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
        self.force_visible = False      # set after a captcha in headless mode
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
        self.browser.ensure(profile=meta.get("profile", ""), headless=headless)

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

    def _check_blocker(self) -> None:
        reason = pr.detect_blocker(self.browser.html())
        if reason:
            raise NeedsUser(f"Possible captcha/challenge on {self.browser.url} ({reason}). "
                            "Solve it in the browser window, then press Continue.")

    # ------------------------------------------------------------------ run
    def run(self, steps: list[dict], reset_data: bool = False) -> RunStats:
        if reset_data:
            self._reset_data()
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

    def run_step(self, step: dict, prefix: str = "") -> Any:
        start = self._tokens()
        self._tok_frames.append(0)
        try:
            return self._run_step(step, prefix)
        finally:
            self._tok_frames.pop()
            if self._tok_frames:                # tell the parent (for_each) what its children used
                self._tok_frames[-1] += self._tokens() - start

    def _run_step(self, step: dict, prefix: str = "") -> Any:
        key = prefix + str(step.get("id", step.get("step_name", "step")))
        current = step
        heals = user_holds = 0
        mark = self._tokens()       # heal calls happen between attempts: counted on the next log line
        while True:
            self.check_stop()
            action = current.get("action", "")
            self.ui.emit("status", self.chat_id, text=f"{key}: {current.get('step_name', action)}")
            try:
                result = self.dispatch(current, key)
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
                    if d == "ask_user":
                        if self.ui.hold(self.chat_id, decision.get("message") or err):
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
            raise StepFailed(f"unknown tool '{action}'")
        if not toolbox.allowed(action, self.task_type):
            raise StepFailed(f"tool '{action}' is not available for {self.task_type} tasks")
        if tool.browser:
            self._ensure_browser()
        return getattr(self, f"act_{action}")(step, key)

    # ---- browser tools
    def act_open_url(self, step: dict, key: str) -> None:
        url = self.render(step.get("url", ""))
        try:
            self.browser.goto(url)
        except Exception:
            fb = self.render(step.get("fallback_url", ""))
            if not fb:
                raise
            self.log(f"{url} failed, trying fallback {fb}")
            self.browser.goto(fb)
        self._check_blocker()

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

    def _local_refind(self, mem: dict, html: str, action: str, target: str) -> Optional[str]:
        """The remembered element moved or its selector changed: find it again among the page's
        elements by tag, stable attributes and text - only when one candidate clearly wins."""
        stored = mem.get("element")
        if not stored:
            return None
        cands = pr.candidates(html, action, target, level=2, limit=80)
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
        reason = pr.detect_blocker(html)
        if reason:
            raise NeedsUser(f"Possible captcha/challenge ({reason}). Solve it in the browser, then Continue.")

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
            cands = pr.candidates(html, action, target, level)
            if not cands:
                continue
            if level == 1:
                pick = pr.obvious_choice(cands, action)
                if pick and self.browser.exists(pick["selector"]):
                    self.stats.local_picks += 1
                    self.log(f"{key}: picked '{pick['text'] or pick['tag']}' without the LLM (clear match)")
                    return self._remember(mem, pick["selector"])
            self.stats.llm_lookups += 1
            ans = self.llm.ask_json("pick", prompts.PICK,
                                    f"Step: {brief}\n{page}\nCandidates:\n{pr.candidates_for_prompt(cands, url)}",
                                    max_tokens=150)
            ans = ans if isinstance(ans, dict) else {}
            if ans.get("need") == "user":
                raise NeedsUser(ans.get("reason") or "The agent needs your help in the browser.")
            try:
                idx = int(ans.get("index", -1))
            except (TypeError, ValueError):
                idx = -1
            if 0 <= idx < len(cands) and self.browser.exists(cands[idx]["selector"]):
                return self._remember(mem, cands[idx]["selector"])

        self.stats.llm_lookups += 1
        ans = self.llm.ask_json("locate", prompts.LOCATE,
                                f"Step: {brief}\n{page}\nOutline:\n{pr.page_outline(html, self.settings.max_page_chars)}",
                                max_tokens=200)
        ans = ans if isinstance(ans, dict) else {}
        sel = ans.get("selector")
        if sel and self.browser.exists(sel):
            return self._remember(mem, sel)
        if ans.get("need") == "user":
            raise NeedsUser(ans.get("reason") or "The agent needs your help in the browser.")
        raise StepFailed(f"element not found: {target}")

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
                cands = pr.candidates_for_prompt(pr.candidates(html, step.get("action", "click"),
                                                               self.render(step.get("target", "")), 2, limit=25), url)
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
        if sigs:
            chosen = [l for l in all_links if l["sig"] in sigs][:limit]
            if chosen:
                self.stats.cache_hits += 1
        if not chosen:
            shown = all_links[:150]
            listing = pr.links_for_prompt(shown, self.browser.url)
            self.stats.llm_lookups += 1
            ans = self.llm.ask_json("pick", prompts.PICK_LINKS,
                                    f"Want: {self.render(step.get('target', ''))} (limit {limit})\n"
                                    f"Page: {pr.short_url(self.browser.url)}\nLinks:\n{listing}", max_tokens=300)
            idxs = ans.get("indices", []) if isinstance(ans, dict) else ans if isinstance(ans, list) else []
            chosen = [shown[int(i)] for i in idxs if str(i).lstrip("-").isdigit() and 0 <= int(i) < len(shown)][:limit]
            # Remember link "shapes" only when they are specific enough to reuse.
            good = set()
            for l in chosen:
                same = sum(1 for x in all_links if x["sig"] == l["sig"])
                if "." in l["sig"] and same <= max(limit * 3, 30):
                    good.add(l["sig"])
            r["link_signatures"] = sorted(good)
        urls = [l["href"] for l in chosen]
        self.vars[step.get("save_as", "links")] = urls
        self.data().setdefault("collected", {})[step.get("save_as", "links")] = urls
        self.log(f"Collected {len(urls)} links")
        if not urls:
            raise StepFailed("no matching links found")
        return urls

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
        done = 0
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
                self.stats.items_failed += 1
                self.log(f"Item failed ({item}): {e}")
            finally:
                self.item = None
        self.log(f"for_each {key}: {done} items processed")
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
        if not records:
            raise StepFailed("nothing to write: no records or processed items yet")
        final = output.write_rows(records, path)
        self.data()["output_file"] = str(final)
        self.log(f"Output written: {final}")
        return str(final)


_missing = [name for name in toolbox.REGISTRY if not hasattr(Executor, f"act_{name}")]
assert not _missing, f"tools without an Executor.act_<name> handler: {_missing}"
