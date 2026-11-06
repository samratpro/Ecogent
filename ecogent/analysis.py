"""
Analysis of collected data files into the final deliverable.

A BM25 relevance filter first keeps only the parts of each page that match the goal (within
settings.analysis_budget_chars). Small inputs then go to the LLM in one call; large ones are
condensed per source first (map, purpose "analyze_map": a job for the cheap model) and the notes
are cached, so a follow-up that only changes the format reuses them. Unchanged sources + request
reuse the previous deliverable without any call.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from . import output, prompts, relevance

if TYPE_CHECKING:
    from .executor import Executor


def _strip_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", t, flags=re.DOTALL)
    return m.group(1) if m else t


class AnalysisEngine:
    def __init__(self, ex: "Executor"):
        self.ex = ex

    def run(self, instructions: str = "", reuse_notes: bool = True) -> Path:
        ex = self.ex
        plan = ex.plan
        files = [f for f in plan.get("data", {}).get("temp_files", []) if Path(f["path"]).exists()]
        if not files:
            from .executor import StepFailed
            raise StepFailed("no collected data to analyze")
        out = plan.get("output", {})
        fmt = output.normalize_format(out.get("format", "md"))
        path = output.output_path(ex.session.output_dir, out.get("filename", "analysis"), fmt)
        goal = plan.get("goal", "")
        wanted = " ".join(x for x in (out.get("instructions", ""), instructions) if x)

        docs = [(f, Path(f["path"]).read_text(encoding="utf-8", errors="replace")) for f in files]
        # Relevance filter (BM25, no model): only the parts of each page that match the goal.
        # "Analyze deeper" (reuse_notes=False) gets twice the budget.
        budget = ex.settings.analysis_budget_chars * (1 if reuse_notes else 2)
        texts, st = relevance.select([t for _, t in docs], f"{goal} {wanted}", budget)
        if st["after"] < st["before"]:
            ex.log(f"Relevance filter: {st['before']:,} -> {st['after']:,} chars "
                   f"({st['chunks_kept']} of {st['chunks_total']} chunks kept)")
            docs = [(f, t) for (f, _), t in zip(docs, texts)]
        total = sum(len(t) for _, t in docs)
        if total <= ex.settings.analysis_direct_chars:
            material = "\n\n---\n\n".join(t for _, t in docs)
        else:
            focus = goal if reuse_notes else f"{goal} | {instructions}"
            material = "\n\n---\n\n".join(self._notes(f, t, focus) for f, t in docs)

        ex.ui.emit("status", ex.chat_id, text=f"Analyzing {len(docs)} sources -> {fmt}")
        tables = fmt in output.TABLE_FORMATS or fmt == "json"
        style = "Markdown" if fmt in ("md", "docx") else "HTML" if fmt == "html" else "plain text"
        if tables:
            system, user = prompts.ANALYZE_ROWS, f"Goal: {goal}\nRequirements: {wanted}\n\nSources:\n{material}"
        else:
            system = prompts.ANALYZE_REDUCE
            user = f"Goal: {goal}\nRequirements: {wanted}\nWrite it as {style}. Cite source URLs.\n\nSources:\n{material}"
        # Same sources + same request = same deliverable: reuse it instead of paying again.
        # (reuse_notes=False means "analyze deeper": always a fresh call.)
        cache = self._final_cache(system, user, "json" if tables else "txt")
        cached = cache.read_text(encoding="utf-8") if reuse_notes and cache.exists() else None
        if cached is not None:
            ex.stats.cache_hits += 1
            ex.log("Sources and request unchanged: reusing the previous analysis (no LLM call)")
        if tables:
            ans = json.loads(cached) if cached is not None else ex.llm.ask_json("analyze", system, user)
            rows = ans.get("rows", []) if isinstance(ans, dict) else ans if isinstance(ans, list) else []
            if cached is None and rows:
                cache.write_text(json.dumps(ans, ensure_ascii=False), encoding="utf-8")
            final = output.write_rows([r for r in rows if isinstance(r, dict)], path)
        else:
            text = cached if cached is not None else _strip_fences(ex.llm.ask("analyze", system, user))
            if cached is None and text.strip():
                cache.write_text(text, encoding="utf-8")
            final = output.write_text(text, path)
        plan.setdefault("data", {})["output_file"] = str(final)
        ex.save_plan()
        ex.log(f"Final output written: {final}")
        return final

    def _final_cache(self, system: str, user: str, ext: str) -> Path:
        notes_dir = self.ex.session.ensure_temp() / "notes"
        notes_dir.mkdir(exist_ok=True)
        key = hashlib.sha1(f"{system}|{user}".encode("utf-8", "replace")).hexdigest()[:16]
        return notes_dir / f"final_{key}.{ext}"

    def _notes(self, f: dict, text: str, focus: str) -> str:
        ex = self.ex
        notes_dir = ex.session.ensure_temp() / "notes"
        notes_dir.mkdir(exist_ok=True)
        # Content hash: changed pages get fresh notes, unchanged pages reuse notes for free.
        key = hashlib.sha1(f"{text}|{focus}".encode("utf-8", "replace")).hexdigest()[:16]
        cache = notes_dir / f"{key}.md"
        if cache.exists():
            ex.stats.cache_hits += 1
            return cache.read_text(encoding="utf-8")
        ex.check_stop()
        notes = ex.llm.ask("analyze_map", prompts.ANALYZE_MAP,
                           f"Goal: {focus}\nSource: {f.get('url')}\n\n{text[: ex.settings.max_page_chars]}",
                           max_tokens=500)
        notes = f"Source: {f.get('url')} ({f.get('title', '')})\n{notes.strip()}"
        cache.write_text(notes, encoding="utf-8")
        return notes
