"""
Ecogent orchestrator: new chats, first plan, execution, follow-ups and reruns.

Flow (how_work.md):
  new chat -> user picks task type -> user prompt + system prompt + type rules -> LLM
  returns plan.json / current_task.json / summary -> agent executes step by step ->
  follow-ups reuse the plan (rerun / heal / extend / reanalyze) to keep tokens low.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from . import output, prompts
from .analysis import AnalysisEngine
from .bridge import UIBridge
from .browser import BrowserError, BrowserSession
from .config import NOT_IMPLEMENTED_TYPES, TASK_LABELS, TASK_TYPES, Settings
from .executor import Executor, StepFailed, StopRequested
from .llm import LLMError, LLMRouter
from .memory import PlanMemory, compact_plan_reference
from .scheduler import validate_rule
from .storage import ChatSession, now_iso, open_session, slugify


def normalize_steps(steps: list, prefix: str = "s") -> list:
    """Give every step a unique id (kept if the LLM provided one)."""
    seen: set = set()
    out = []
    for i, st in enumerate(steps or [], 1):
        if not isinstance(st, dict):
            continue
        sid = str(st.get("id") or f"{prefix}{i}")
        while sid in seen:
            sid += "_"
        seen.add(sid)
        st = {**st, "id": sid}
        if isinstance(st.get("steps"), list):
            st["steps"] = normalize_steps(st["steps"], prefix=f"{sid}_")
        out.append(st)
    return out


# ---- follow-ups answered without an LLM call
FORMAT_WORDS = {"docx": "docx", "word": "docx", "md": "md", "markdown": "md", "csv": "csv", "excel": "xlsx",
                "xlsx": "xlsx", "spreadsheet": "xlsx", "json": "json", "txt": "txt"}
FORMAT_FILLER = {"give", "me", "the", "same", "as", "a", "an", "in", "into", "to", "it", "this", "that", "please",
                 "pls", "now", "convert", "export", "save", "file", "document", "doc", "format", "output", "version",
                 "data", "result", "results", "report", "can", "could", "would", "you", "i", "want", "need", "also",
                 "send", "make", "create", "get", "of", "one", "copy", "instead", "thanks", "thank", "just", "but",
                 "like", "for", "and", "too", "file", "type"}
RERUN_TRIGGERS = {"run", "rerun", "again", "repeat", "refresh"}
RERUN_WORDS = RERUN_TRIGGERS | {"it", "the", "task", "same", "please", "pls", "once", "more", "now", "with", "fresh",
                                "data", "one", "time", "do", "this", "that", "can", "you", "and"}


def apply_step_changes(steps: list, changes: dict) -> list:
    """Apply a follow-up patch {"replace": [...], "insert_after": {id|"^": [...]}, "remove": [...]}.
    Unchanged steps keep their ids (and with them their cached selectors); new steps get ids
    that cannot collide with existing ones."""
    def all_ids(items: list) -> set:
        out = set()
        for st in items:
            if isinstance(st, dict):
                out.add(str(st.get("id")))
                out |= all_ids(st.get("steps") or [])
        return out

    used = all_ids(steps)
    counter = [0]

    def fresh(st: dict) -> dict:
        st = dict(st)
        if not st.get("id") or (str(st["id"]) in used and st.get("_new", True)):
            counter[0] += 1
            while f"n{counter[0]}" in used:
                counter[0] += 1
            st["id"] = f"n{counter[0]}"
        used.add(str(st["id"]))
        st.pop("_new", None)
        return st

    replace = {str(st.get("id")): st for st in (changes.get("replace") or []) if isinstance(st, dict) and st.get("id")}
    remove = {str(x) for x in (changes.get("remove") or [])}
    inserts = {str(k): [fresh(st) for st in v if isinstance(st, dict)]
               for k, v in (changes.get("insert_after") or {}).items() if isinstance(v, list)}

    def walk(items: list) -> list:
        out = []
        for st in items:
            if not isinstance(st, dict):
                continue
            sid = str(st.get("id"))
            if sid in remove:
                continue
            new = {**st, **replace[sid], "id": st.get("id")} if sid in replace else dict(st)
            if isinstance(new.get("steps"), list):
                new["steps"] = walk(new["steps"])
            out.append(new)
            out.extend(inserts.get(sid, []))
        return out

    return inserts.get("^", []) + walk(steps)


def _host(url: str) -> str:
    try:
        return urlparse(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


class EcogentAgent:
    def __init__(self, settings: Settings, ui: UIBridge, stop: Optional[threading.Event] = None):
        self.settings = settings
        self.ui = ui
        self.stop = stop or threading.Event()
        self.browser = BrowserSession(settings, log=lambda t: ui.log(t))
        self._memory: Optional[PlanMemory] = None
        self.on_schedule: Optional[Callable[[str, dict], None]] = None   # set by the app

    # ------------------------------------------------------------------ helpers
    def reload(self, settings: Settings) -> None:
        self.browser.close()
        self.settings = settings
        self.browser = BrowserSession(settings, log=lambda t: self.ui.log(t))
        self._memory = None

    @property
    def memory(self) -> PlanMemory:
        if self._memory is None:
            self._memory = PlanMemory(self.settings.home_path, self.settings.use_vector_memory, self.ui.log)
        return self._memory

    def session(self, chat_id: str) -> ChatSession:
        s = open_session(self.settings, chat_id)
        if s is None:
            raise ValueError(f"chat {chat_id} not found")
        return s

    def router(self, s: ChatSession) -> LLMRouter:
        def on_usage(purpose, resp):
            s.add_usage(purpose, resp.provider, resp.model, resp.input_tokens, resp.output_tokens,
                        getattr(resp, "cached_input_tokens", 0), getattr(resp, "cache_write_tokens", 0))
            self.ui.emit("usage", s.id)
        return LLMRouter(self.settings, on_usage, log=lambda t: self.ui.log(t, s.id))

    def say(self, s: ChatSession, text: str) -> None:
        s.add_message("agent", text)
        self.ui.message(s.id, "agent", text)

    def executor(self, s: ChatSession) -> Executor:
        return Executor(s, self.browser, self.router(s), self.ui, self.settings, self.stop)

    # ------------------------------------------------------------------ chats
    def new_chat(self, task_type: str, title: str = "", profile: str = "", headless: Optional[bool] = None) -> ChatSession:
        if task_type not in TASK_TYPES:
            raise ValueError(f"unknown task type {task_type}")
        s = ChatSession.create(self.settings.chats_path, self.settings.temp_path, self.settings.output_path,
                               task_type, title or f"New {TASK_LABELS[task_type]} task", profile,
                               self.settings.headless if headless is None else headless)
        self.ui.emit("chats", s.id)
        return s

    def delete_chat(self, chat_id: str) -> None:
        s = open_session(self.settings, chat_id)
        if s:
            s.delete()
        try:
            self.memory.remove(chat_id)
        except Exception:
            pass
        self.ui.emit("chats")

    def classify(self, text: str, s: Optional[ChatSession] = None) -> dict:
        """Task type + intent, used when Ecogent is called by another agent/tool."""
        router = self.router(s) if s else LLMRouter(self.settings)
        ans = router.ask_json("classify", prompts.CLASSIFY, text, max_tokens=150)
        ans = ans if isinstance(ans, dict) else {}
        if ans.get("task_type") not in TASK_TYPES or ans.get("task_type") in NOT_IMPLEMENTED_TYPES:
            ans["task_type"] = "others"
        return ans

    # ------------------------------------------------------------------ entry point for a user message
    def handle_message(self, chat_id: str, text: str) -> None:
        s = self.session(chat_id)
        s.add_message("user", text)
        if s.meta.get("task_type") in NOT_IMPLEMENTED_TYPES:
            self.say(s, f"{TASK_LABELS[s.meta['task_type']]} tasks are not implemented yet.")
            return
        try:
            if not s.current_task:
                self.initialize(s, text)
            else:
                self.follow_up(s, text)
        except LLMError as e:
            s.update_meta(status="error")
            self.say(s, f"LLM error: {e}\nCheck Settings > Main LLM.")
        finally:
            self.ui.emit("chats", s.id)

    # ------------------------------------------------------------------ first plan
    def initialize(self, s: ChatSession, text: str) -> None:
        meta = s.meta
        ttype = meta.get("task_type", "others")
        ref_session = None
        reference = ""
        try:
            hit = self.memory.similar(ttype, text, exclude=s.id)
            if hit and hit[1] >= 0.75:
                ref_session = open_session(self.settings, hit[0])
                if ref_session and ref_session.current_task:
                    reference = compact_plan_reference(ref_session.plan, ref_session.current_task)
                    self.ui.log(f"Reusing a similar earlier plan ({hit[0]}, similarity {hit[1]:.2f})", s.id)
                else:
                    ref_session = None
        except Exception as e:
            self.ui.log(f"Memory lookup skipped: {e}", s.id)

        self.ui.emit("status", s.id, text="Planning with LLM...")
        system = prompts.system(ttype, prompts.INIT_SCHEMA)
        user = (f"Task type: {ttype}\nToday: {date.today().isoformat()}\nUser request: {text}\n"
                f"Known user info fields: {list(s.user_info().keys())}\n"
                f"Selected folder for file tools: {meta.get('work_folder') or 'none (output folder)'}\n"
                f"Browser profile in use: {meta.get('profile') or 'none (fresh temporary profile)'}")
        if reference:
            user += ("\n\nA similar task was solved before. Reuse or adapt it and keep the same step ids "
                     f"for unchanged steps:\n{reference}")
        ans = self.router(s).ask_json("plan", system, user, max_tokens=4000)
        if not isinstance(ans, dict) or not isinstance(ans.get("current_task"), list) or not ans["current_task"]:
            raise LLMError("planner did not return a current_task list")

        plan = ans.get("plan") or {}
        plan.update(task_type=ttype, request=text, created=now_iso())
        steps = normalize_steps(ans["current_task"])
        if ref_session:
            self._inherit_memory(plan, steps, ref_session)
        s.save_plan(plan)
        s.save_task(steps)
        s.set_summary(ans.get("summary", ""))
        s.update_meta(title=ans.get("title") or meta.get("title"), status="planned")
        self.say(s, ans.get("reply") or f"Plan ready: {len(steps)} steps.")
        try:
            self.memory.add(s.id, ttype, f"{text}\n{plan.get('goal', '')}")
        except Exception:
            pass
        self.ui.emit("files", s.id)
        self.ui.emit("chats", s.id)

        if not self.prepare_requirements(s):
            self.say(s, "Waiting: requirements were not completed. Send a message or press Run when ready.")
            return
        self.execute(s, steps, reset_data=True)

    def _inherit_memory(self, plan: dict, steps: list, ref: ChatSession) -> None:
        """Copy cached selectors/patterns from a similar earlier chat (same site, same step)."""
        rp, old = ref.plan, {st.get("id"): st for st in ref.current_task}
        if _host(plan.get("destination", {}).get("start_url", "")) != _host(rp.get("destination", {}).get("start_url", "")):
            return
        old_exec = rp.get("execution", {}).get("steps", {})
        new_exec = plan.setdefault("execution", {}).setdefault("steps", {})
        copied = 0
        for st in steps:
            o = old.get(st["id"])
            if o and o.get("action") == st.get("action") and o.get("target") == st.get("target"):
                for key, rec in old_exec.items():
                    if key == st["id"] or key.startswith((st["id"] + ".", st["id"] + "@")):
                        new_exec[key] = {k: v for k, v in rec.items()
                                         if k in (*Executor.MEMORY_FIELDS, "link_signatures")}
                        copied += 1
        if rp.get("pattern") and plan.get("task_type") == "scraping":
            plan["pattern"] = {**rp["pattern"], "confirmed": False}
        if copied:
            self.ui.log(f"Inherited {copied} cached selectors from {ref.id}", ref.id)

    # ------------------------------------------------------------------ automation requirements
    def prepare_requirements(self, s: ChatSession) -> bool:
        req = s.plan.get("requirements") or {}
        if req.get("needs_login"):
            name = slugify(req.get("profile_name") or s.meta.get("profile") or s.meta.get("title", "site"), 30)
            if s.meta.get("profile"):
                name = s.meta["profile"]
            if name not in self.browser.list_profiles():
                url = req.get("login_url") or s.plan.get("destination", {}).get("start_url", "")
                ok = self.ui.confirm(s.id, (
                    f"This task needs a logged-in browser.\n\nEcogent will open a browser window with a new profile "
                    f"'{name}' at:\n{url}\n\nLog in yourself (solve any captcha), then CLOSE that browser window. "
                    "The cookies are kept in the profile and reused on every run.\n\nOpen it now?"))
                if not ok:
                    return False
                self.ui.emit("status", s.id, text="Waiting for you to log in and close the browser...")
                self.browser.setup_profile(name, url)
            s.update_meta(profile=name)

        fields = [f for f in (req.get("user_info_fields") or []) if isinstance(f, str)]
        missing = [f for f in fields if f not in s.user_info()]
        if missing:
            got = self.ui.ask_user_info(s.id, missing, "Information this automation will use (stored only in this chat folder).")
            if got is None:
                return False
            info = s.user_info()
            info.update(got)
            s.save_user_info(info)
        return True

    # ------------------------------------------------------------------ execution
    def execute(self, s: ChatSession, steps: list, reset_data: bool = False, scheduled: bool = False) -> str:
        ex = self.executor(s)
        s.update_meta(status="running")
        self.ui.emit("chats", s.id)
        status, detail = "done", ""
        try:
            stats = ex.run(steps, reset_data=reset_data)
            status = "done" if not stats.steps_failed else "partial"
            detail = stats.line()
        except StopRequested as e:
            status, detail = "stopped", str(e)
        except StepFailed as e:
            status, detail = "failed", str(e)
        except BrowserError as e:
            status, detail = "failed", f"Browser: {e}"
        except LLMError as e:
            status, detail = "failed", f"LLM: {e}"
        finally:
            s.update_meta(status=status, last_run=now_iso())
            self.ui.emit("chats", s.id)
            self.ui.emit("files", s.id)

        u = s.usage
        out = ex.plan.get("data", {}).get("output_file", "")
        msg = (f"Run {status}{' (scheduled)' if scheduled else ''}: {detail}\n"
               f"Tokens so far in this chat: {u.get('input_tokens', 0)} in / {u.get('output_tokens', 0)} out "
               f"({u.get('calls', 0)} LLM calls)")
        if out:
            msg += f"\nOutput: {out}"
        self.say(s, msg)
        if status == "done" and not scheduled:
            self._offer_schedule(s)
        return status

    def _offer_schedule(self, s: ChatSession) -> None:
        sched = (s.plan.get("requirements") or {}).get("schedule")
        if not isinstance(sched, dict) or not self.on_schedule or s.meta.get("scheduled"):
            return
        try:
            minutes, daily = validate_rule(sched.get("every_minutes"), sched.get("daily_at") or "")
        except ValueError as e:
            self.ui.log(f"Schedule suggested by the planner ignored: {e}", s.id)
            return
        sched = {"every_minutes": minutes, "daily_at": daily}
        rule = f"every {minutes} minutes" if minutes else f"daily at {daily}"
        if self.ui.confirm(s.id, f"Run this automation periodically ({rule})?"):
            self.on_schedule(s.id, sched)
            s.update_meta(scheduled=True)
            self.say(s, f"Scheduled: {rule}. Manage it in Schedules.")

    def rerun(self, chat_id: str, scheduled: bool = False) -> None:
        s = self.session(chat_id)
        if not s.current_task:
            self.say(s, "Nothing to run yet - send a task first.")
            return
        if not scheduled and not self.prepare_requirements(s):
            return
        self.execute(s, s.current_task, reset_data=True, scheduled=scheduled)

    # ------------------------------------------------------------------ follow-ups
    def _local_follow_up(self, s: ChatSession, text: str) -> bool:
        """Follow-ups that need no LLM call: "run it again" and "same as docx/csv/...".
        Returns True when handled."""
        words = re.findall(r"[a-z]+", text.lower())
        if not words or len(words) > 14:
            return False
        if set(words) <= RERUN_WORDS and set(words) & RERUN_TRIGGERS:
            self.say(s, "Running the task again with the saved plan.")
            self.rerun(s.id)
            return True
        formats = {FORMAT_WORDS[w] for w in words if w in FORMAT_WORDS}
        rest = [w for w in words if w not in FORMAT_WORDS and w not in FORMAT_FILLER]
        if len(formats) != 1 or rest:
            return False
        fmt = formats.pop()
        plan = s.plan
        data = plan.get("data", {})
        old_out = Path(data.get("output_file") or "")
        if not data.get("records_file") and not (data.get("output_file") and old_out.exists()):
            return False
        plan.setdefault("output", {})["format"] = fmt
        s.save_plan(plan)
        ex = self.executor(s)
        try:
            if data.get("records_file"):
                path = ex.write_output()                  # scraped records in a new format
            elif old_out.suffix.lower() in (".md", ".txt") and fmt in ("md", "txt", "docx"):
                text_out = old_out.read_text(encoding="utf-8", errors="replace")
                out = ex.plan.get("output", {})
                path = output.write_text(text_out, output.output_path(s.output_dir, out.get("filename", "analysis"), fmt))
                ex.data()["output_file"] = str(path)
                ex.save_plan()
            else:
                # Needs a new layout (e.g. md -> table): analysis, but no follow-up planning call.
                self.reanalyze(s, f"Same content, delivered as {fmt}.", reuse_notes=True)
                return True
        except (StepFailed, OSError) as e:
            self.ui.log(f"Local format change failed ({e}); asking the LLM", s.id)
            return False
        s.update_meta(status="done")
        self.say(s, f"Converted without the LLM: {path}")
        self.ui.emit("files", s.id)
        return True

    def follow_up(self, s: ChatSession, text: str) -> None:
        if self._local_follow_up(s, text):
            return
        plan, steps = s.plan, s.current_task
        ttype = s.meta.get("task_type", "others")
        exec_status = {k: {"status": v.get("status"), "error": v.get("error", "")[:120]}
                       for k, v in plan.get("execution", {}).get("steps", {}).items() if v.get("status")}
        data = plan.get("data", {})
        collected = {"data_files": [f.get("title", "")[:80] for f in data.get("temp_files", [])],
                     "records_count": data.get("records_count"), "output_file": data.get("output_file")}
        recent = s.chat.get("messages", [])[-6:]
        user = "\n".join([
            f"Existing plan: {compact_plan_reference(plan, steps)}",
            f"Step status: {json.dumps(exec_status)[:3000]}",
            f"Collected data: {json.dumps(collected, ensure_ascii=False)[:2000]}",
            f"Memory summary: {s.chat.get('summary', '')}",
            f"Recent messages: {json.dumps([{m['role']: m['text'][:300]} for m in recent], ensure_ascii=False)}",
            f"New user message: {text}",
        ])
        system = prompts.system(ttype, prompts.FOLLOWUP_SCHEMA)
        self.ui.emit("status", s.id, text="Thinking about the follow-up...")
        ans = self.router(s).ask_json("followup", system, user, max_tokens=4000)
        ans = ans if isinstance(ans, dict) else {"decision": "reply", "reply": str(ans)}
        decision = ans.get("decision", "reply")

        s.set_summary(ans.get("summary", ""))
        if isinstance(ans.get("plan_updates"), dict) and ans["plan_updates"]:
            plan = s.plan
            for k, v in ans["plan_updates"].items():
                plan[k] = {**plan[k], **v} if isinstance(plan.get(k), dict) and isinstance(v, dict) else v
            if decision == "extend" and ("scrape" in ans["plan_updates"] or "destination" in ans["plan_updates"]):
                # Different category / site: keep the old pattern only as a starting point.
                if plan.get("pattern"):
                    plan["pattern"]["confirmed"] = False
            s.save_plan(plan)
        self.say(s, ans.get("reply") or f"Decision: {decision}")
        self.ui.emit("files", s.id)

        if decision == "reply":
            return
        if decision == "rerun":
            self.execute(s, s.current_task, reset_data=True)
        elif decision in ("heal", "extend"):
            if ans.get("current_task"):
                new_steps = normalize_steps(ans["current_task"])
            elif isinstance(ans.get("step_changes"), dict):
                new_steps = apply_step_changes(s.current_task, ans["step_changes"])
            else:
                new_steps = []
            if not new_steps:
                self.say(s, "The planner returned no steps; running the existing ones.")
                new_steps = s.current_task
            s.save_task(new_steps)
            self.ui.emit("files", s.id)
            if self.prepare_requirements(s):
                self.execute(s, new_steps, reset_data=(decision == "heal"))
        elif decision == "reanalyze":
            self.reanalyze(s, ans.get("analysis_instructions", text), bool(ans.get("reuse_notes", True)))

    def reanalyze(self, s: ChatSession, instructions: str, reuse_notes: bool = True) -> None:
        ex = self.executor(s)
        try:
            if ex.plan.get("data", {}).get("records_file"):
                path = ex.write_output()            # scraped data in a new format: no LLM needed
            else:
                path = AnalysisEngine(ex).run(instructions, reuse_notes=reuse_notes)
            s.update_meta(status="done")
            self.say(s, f"Output updated: {path}")
        except StepFailed as e:
            self.say(s, f"Cannot reanalyze ({e}); running the task again.")
            self.execute(s, s.current_task, reset_data=True)
        finally:
            self.ui.emit("files", s.id)
