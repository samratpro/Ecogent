"""
Relevance filter for analysis input (pure Python BM25, no model).

Collected pages are split into paragraph chunks, every chunk is scored against the goal with
BM25, and only the best chunks are sent to the LLM, within a character budget shared fairly
by all sources. Each source keeps its first chunk (title / intro) and the kept chunks stay in
page order, so the text still reads naturally.
"""

from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""a an and are as at be but by can do does for from give has have how i in into is it its
me my of on or our please show so summarize summarise summary that the their them then there these
they this to us want was we were what when where which who why will with write you your md file docx
csv json xlsx txt report document output make create find search get list all about between more
most also each other than any some such only own same very just should would could against""".split())


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 1 and w not in STOP]


def _stem(w: str) -> str:
    """Tiny suffix stripper: 'agents' ~ 'agent', 'browsing' ~ 'brows'."""
    for suf in ("ingly", "edly", "ing", "ies", "ied", "es", "ed", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def chunks(text: str, target: int = 600) -> list[str]:
    """Paragraph chunks of about `target` chars (short lines are merged, long ones split)."""
    out, cur = [], ""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        while len(line) > target * 2:                       # a giant paragraph: split at a sentence end
            cut = line.rfind(". ", 0, target * 2)
            cut = cut + 1 if cut > target // 2 else target * 2
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:cut].strip())
            line = line[cut:].strip()
        if cur and len(cur) + len(line) + 1 > target:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    q = {_stem(w) for w in tokens(query)}
    if not q or not docs:
        return [0.0] * len(docs)
    toks = [[_stem(w) for w in tokens(d)] for d in docs]
    n = len(docs)
    avg = sum(len(t) for t in toks) / n or 1.0
    df = Counter(w for t in toks for w in set(t) if w in q)
    scores = []
    for t in toks:
        tf = Counter(w for w in t if w in q)
        s = 0.0
        for w, f in tf.items():
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(t) / avg))
        scores.append(s)
    return scores


def select(sources: list[str], query: str, budget: int) -> tuple[list[str], dict]:
    """Shrink `sources` (one text per source) to about `budget` chars in total.
    Returns (new texts, stats). Sources already within their share are kept whole."""
    total = sum(len(s) for s in sources)
    stats = {"before": total, "after": total, "chunks_total": 0, "chunks_kept": 0}
    if budget <= 0 or total <= budget or not sources:
        return sources, stats

    split = [chunks(s) for s in sources]
    flat = [(i, j, c) for i, cs in enumerate(split) for j, c in enumerate(cs)]
    scores = bm25_scores(query, [c for _, _, c in flat])
    by_source: dict[int, list[tuple[float, int, str]]] = {i: [] for i in range(len(sources))}
    for (i, j, c), s in zip(flat, scores):
        by_source[i].append((s, j, c))

    # Fair shares: small sources keep everything, their unused share goes to the larger ones.
    share, remaining = {}, budget
    pending = sorted(range(len(sources)), key=lambda i: len(sources[i]))
    while pending:
        fair = remaining // len(pending)
        i = pending.pop(0)
        share[i] = min(len(sources[i]), fair)
        remaining -= share[i]

    out = []
    for i, items in by_source.items():
        if len(sources[i]) <= share[i]:
            out.append(sources[i])
            stats["chunks_total"] += len(items)
            stats["chunks_kept"] += len(items)
            continue
        keep, used = {0}, len(items[0][2]) if items else 0         # first chunk: title / intro
        has_hits = any(s > 0 for s, _, _ in items)
        ranked = sorted(items, key=lambda t: (-t[0], t[1])) if has_hits else sorted(items, key=lambda t: t[1])
        for s, j, c in ranked:
            if j in keep:
                continue
            if used + len(c) > share[i]:
                continue
            keep.add(j)
            used += len(c)
        kept = [c for s, j, c in sorted(items, key=lambda t: t[1]) if j in keep]
        stats["chunks_total"] += len(items)
        stats["chunks_kept"] += len(kept)
        out.append("\n".join(kept) + ("\n[...less relevant parts omitted]" if len(kept) < len(items) else ""))
    stats["after"] = sum(len(s) for s in out)
    return out, stats
