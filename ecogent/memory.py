"""
Plan memory across chats.

When a new chat looks like an earlier one, the earlier plan is offered to the LLM
as a reference and its cached selectors are copied over, so the new chat starts
with warm execution memory. Uses ChromaDB when available, else fuzzy matching.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Callable, Optional

from .storage import read_json, write_json


class PlanMemory:
    def __init__(self, home: Path, use_vector: bool = True, log: Callable[[str], None] = print):
        self.index_file = Path(home) / "plan_index.json"
        self.log = log
        self._col = None
        if use_vector:
            try:
                import chromadb
                client = chromadb.PersistentClient(path=str(Path(home) / "chroma"))
                self._col = client.get_or_create_collection("ecogent_plans", metadata={"hnsw:space": "cosine"})
            except Exception as e:
                self.log(f"Vector memory unavailable ({e}); using fuzzy matching")

    def add(self, chat_id: str, task_type: str, text: str) -> None:
        index = read_json(self.index_file, {})
        index[chat_id] = {"task_type": task_type, "text": text}
        write_json(self.index_file, index)
        if self._col is not None:
            try:
                self._col.upsert(ids=[chat_id], documents=[text], metadatas=[{"task_type": task_type}])
            except Exception as e:
                self.log(f"Vector memory write failed: {e}")

    def remove(self, chat_id: str) -> None:
        index = read_json(self.index_file, {})
        if index.pop(chat_id, None) is not None:
            write_json(self.index_file, index)
        if self._col is not None:
            try:
                self._col.delete(ids=[chat_id])
            except Exception:
                pass

    def similar(self, task_type: str, text: str, exclude: str = "") -> Optional[tuple[str, float]]:
        """Return (chat_id, similarity 0..1) of the closest earlier task of the same type."""
        if self._col is not None:
            try:
                res = self._col.query(query_texts=[text], n_results=3, where={"task_type": task_type})
                for cid, dist in zip(res["ids"][0], res["distances"][0]):
                    if cid != exclude:
                        return cid, max(0.0, 1.0 - float(dist))
                return None
            except Exception as e:
                self.log(f"Vector memory query failed: {e}")
        best = None
        for cid, item in read_json(self.index_file, {}).items():
            if cid == exclude or item.get("task_type") != task_type:
                continue
            score = difflib.SequenceMatcher(None, text.lower(), item.get("text", "").lower()).ratio()
            if not best or score > best[1]:
                best = (cid, score)
        return best


def _shorten(value, limit: int):
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 3] + "..."
    if isinstance(value, list):
        return [_shorten(v, limit) for v in value]
    if isinstance(value, dict):
        return {k: _shorten(v, limit) for k, v in value.items()}
    return value


def compact_plan_reference(plan: dict, steps: list, max_chars: int = 6000) -> str:
    """Plan + every step as VALID JSON. Long texts are shortened; steps are never dropped,
    because the LLM rewrites the full step list from this view."""
    keep = {k: plan.get(k) for k in ("goal", "destination", "output", "scrape", "requirements") if plan.get(k)}
    data = {"plan": keep, "current_task": steps}
    text = json.dumps(data, ensure_ascii=False)
    for limit in (300, 160, 80):
        if len(text) <= max_chars:
            break
        text = json.dumps(_shorten(data, limit), ensure_ascii=False)
    return text
