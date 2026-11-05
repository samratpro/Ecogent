"""
Analysis of collected data files into the final deliverable.

Small inputs go to the LLM in one call. Large inputs are condensed per source first
(map) and the notes are cached in the temp folder, so a follow-up that only changes
the format reuses them instead of re-reading every source.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from . import output, prompts

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
        total = sum(len(t) for _, t in docs)
        if total <= ex.settings.analysis_direct_chars:
            material = "\n\n---\n\n".join(t for _, t in docs)
        else:
            focus = goal if reuse_notes else f"{goal} | {instructions}"
            material = "\n\n---\n\n".join(self._notes(f, t, focus) for f, t in docs)

        ex.ui.emit("status", ex.chat_id, text=f"Analyzing {len(docs)} sources -> {fmt}")
        if fmt in output.TABLE_FORMATS or fmt == "json":
            ans = ex.llm.ask_json("analyze", prompts.ANALYZE_ROWS,
                                  f"Goal: {goal}\nRequirements: {wanted}\n\nSources:\n{material}")
            rows = ans.get("rows", []) if isinstance(ans, dict) else ans if isinstance(ans, list) else []
            final = output.write_rows([r for r in rows if isinstance(r, dict)], path)
        else:
            style = "Markdown" if fmt in ("md", "docx") else "HTML" if fmt == "html" else "plain text"
            text = ex.llm.ask("analyze", prompts.ANALYZE_REDUCE,
                              f"Goal: {goal}\nRequirements: {wanted}\nWrite it as {style}. "
                              f"Cite source URLs.\n\nSources:\n{material}")
            final = output.write_text(_strip_fences(text), path)
        plan.setdefault("data", {})["output_file"] = str(final)
        ex.save_plan()
        ex.log(f"Final output written: {final}")
        return final

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
        notes = ex.llm.ask("analyze", prompts.ANALYZE_MAP,
                           f"Goal: {focus}\nSource: {f.get('url')}\n\n{text[: ex.settings.max_page_chars]}",
                           max_tokens=900)
        notes = f"Source: {f.get('url')} ({f.get('title', '')})\n{notes.strip()}"
        cache.write_text(notes, encoding="utf-8")
        return notes
