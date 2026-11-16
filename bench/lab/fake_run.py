"""
Plumbing test of bench/drift_bench.py with a scripted fake LLM (no API key, no cost): runs the
papers (analysis) and jobs (automation) tasks for the main variants on a few drift levels and checks
that every row is written and scored. The fake picks elements by word overlap - far weaker than a
real model - so its success numbers mean nothing; only the plumbing is tested. Prints "FAKE RUN OK".

    python -m bench.lab.fake_run <scratch dir>
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from ecogent import llm as L, prompts as P
from ecogent.config import Settings

SCRATCH = Path(sys.argv[1] if len(sys.argv) > 1 else "bench/results/fake")
SKIP = {"button", "box", "field", "link", "the", "and", "search", "click", "fill"}


def _shop_truth() -> dict:
    """Product names only (to find them in the page text); prices are always read from the page."""
    from ecogent import test_shop
    return test_shop.lab("/truth", timeout=10)


def _pick(user: str) -> dict:
    step = json.loads(re.search(r"Step: (\{.*?\})\n", user).group(1))
    target = f"{step.get('target', '')} {step.get('step_name', '')}".lower()
    words = {w for w in re.findall(r"[a-z]+", target) if len(w) > 2} - SKIP
    if "search" in target:
        words |= {"search"}
    lines = user.split("Candidates:\n")[1].splitlines()
    fill = step.get("action") == "fill"
    best, idx = 0.0, -1
    for i, line in enumerate(lines):
        low = line.lower()
        kind_ok = ("<input" in low or "<textarea" in low) if fill else \
            any(t in low for t in ("<button", "<a ", "type=submit", "<input"))
        if not kind_ok:
            continue
        score = sum(1 for w in words if w in low) + 0.01
        if score > best:
            best, idx = score, i
    return {"index": idx}


def fake_complete(self, system, messages, max_tokens=None, json_mode=False):
    user = messages[-1]["content"]

    def r(obj):
        return L.LLMResponse(obj if isinstance(obj, str) else json.dumps(obj), len(system + user) // 4, 40, "fake", "fake")
    if P.INIT_SCHEMA in system:
        if "localhost:3010" in user and "Home & Kitchen" in user:     # test shop: nw_kitchen_price_range
            base = "http://localhost:3010"
            return r({"title": "Kitchen prices", "summary": "s", "reply": "ok",
                      "plan": {"goal": "cheapest and most expensive in-stock kitchen product",
                               "destination": {"start_url": base + "/c/home-kitchen"},
                               "output": {"format": "md", "filename": "report.md"}},
                      "current_task": [
                          {"id": "s1", "action": "open_url", "url": base + "/c/home-kitchen?instock=1&sort=price-asc&per=48"},
                          {"id": "s2", "action": "get_page_data"},
                          {"id": "s3", "action": "analyze", "instructions": "cheapest and most expensive product with prices"}]})
        base = re.search(r"(http://127\.0\.0\.1:\d+)", user).group(1)
        if "/papers/" in user:
            return r({"title": "Papers", "summary": "s", "reply": "ok",
                      "plan": {"goal": "summarize papers", "destination": {"start_url": base + "/papers/"},
                               "output": {"format": "md", "filename": "report.md"}},
                      "current_task": [
                          {"id": "s1", "action": "open_url", "url": base + "/papers/"},
                          {"id": "s2", "action": "fill", "target": "search papers box", "value": "web agent caching"},
                          {"id": "s3", "action": "click", "target": "Search button"},
                          {"id": "s4", "action": "collect_links", "target": "paper result titles", "limit": 3,
                           "save_as": "papers"},
                          {"id": "s5", "action": "for_each", "source": "papers", "dedupe": True, "steps": [
                              {"id": "a", "action": "open_url", "url": "{{item}}"},
                              {"id": "b", "action": "get_page_data"}]},
                          {"id": "s6", "action": "analyze", "instructions": "title and main result"}]})
        if "/jobs/" in user:
            return r({"title": "Jobs", "summary": "s", "reply": "ok",
                      "plan": {"goal": "apply to python jobs", "destination": {"start_url": base + "/jobs/"},
                               "requirements": {"needs_login": False, "user_info_fields": ["full_name", "email"]}},
                      "current_task": [
                          {"id": "s1", "action": "open_url", "url": base + "/jobs/"},
                          {"id": "s2", "action": "fill", "target": "job title or skill search box", "value": "python"},
                          {"id": "s3", "action": "click", "target": "Search button"},
                          {"id": "s4", "action": "collect_links", "target": "job titles in the results", "limit": 10,
                           "save_as": "jobs"},
                          {"id": "s5", "action": "for_each", "source": "jobs", "dedupe": True, "steps": [
                              {"id": "a", "action": "open_url", "url": "{{item}}"},
                              {"id": "b", "action": "click", "target": "Apply link"},
                              {"id": "c", "action": "fill", "target": "Full name input", "value": "{{user.full_name}}"},
                              {"id": "d", "action": "fill", "target": "Email input", "value": "{{user.email}}"},
                              {"id": "e", "action": "click", "target": "Submit application button"}]}]})
        raise AssertionError("fake: unknown task prompt")
    if system == P.PICK:
        return r(_pick(user))
    if system == P.PICK_LINKS:
        return r({"indices": [int(m.group(1)) for m in re.finditer(r"\[(\d+)\][^\n]*/(?:papers/p|jobs/j)/", user)]})
    if system == P.LOCATE:
        return r({"selector": None})
    if system == P.RESCUE:
        return r({"do": "give_up", "reason": "fake model"})
    if P.HEAL in system:
        return r({"decision": "skip"})
    if system in (P.ANALYZE_REDUCE, P.ANALYZE_MAP) and "most expensive" in user:
        # Test shop: read name + price pairs from the PAGE TEXT it was given (never from the ground truth), so a
        # stale cached page would give a stale answer and fail the oracle.
        names = [p["name"] for p in _shop_truth()["products"] if p["category"] == "home-kitchen"]
        pairs = []
        for n in sorted(names, key=len, reverse=True):
            m = re.search(re.escape(n) + r"[^$]{0,200}?\$(\d+\.\d\d)", user)
            if m and all(n not in q for q, _ in pairs):
                pairs.append((n, float(m.group(1))))
        if not pairs:
            return r("# Report\nNo products found.")
        lo, hi = min(pairs, key=lambda x: x[1]), max(pairs, key=lambda x: x[1])
        return r(f"# Report\nCheapest: {lo[0]} at ${lo[1]:.2f}.\nMost expensive: {hi[0]} at ${hi[1]:.2f}.")
    if system in (P.ANALYZE_REDUCE, P.ANALYZE_MAP):
        found = re.findall(r"Main result: ([^\n]+)", user)
        return r("# Report\n" + "\n".join(f"- {f}" for f in found))
    if system == P.VALIDATE:
        return r({"ok": True, "problems": ""})
    raise AssertionError("fake: unexpected prompt " + system[:60])


def main() -> None:
    L.LLMClient.complete = fake_complete

    def load():
        s = Settings()
        s.home = str(SCRATCH / "home")
        s.main_llm.api_key = "x"
        s.use_vector_memory = False
        s.ensure_dirs()
        return s
    Settings.load = staticmethod(load)
    from bench import drift_bench
    out = SCRATCH / "drift.csv"
    out.unlink(missing_ok=True)
    sys.argv = ["drift_bench", "--tasks", "papers_caching,jobs_python", "--variants", "ecogent,compile_only,nocache",
                "--levels", "0,2,4", "--seeds", "1", "--price", "fake=1,2", "--out", str(out), "--headless",
                "--port", "8792", "--debug-port", "9281"]
    drift_bench.main()
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    per_cell = {"ecogent": 1 + 3 * 2, "compile_only": 1 + 3 * 2, "nocache": 1 + 3}
    expected = 2 * sum(per_cell.values())
    assert len(rows) == expected, (len(rows), expected)
    assert all(r["cost_usd"] != "" for r in rows), "unpriced rows"
    cold = [r for r in rows if r["phase"] == "cold"]
    assert all(int(r["calls"]) > 0 for r in cold), "cold runs must plan"
    eco_l0 = [r for r in rows if r["variant"] == "ecogent" and r["level"] == "0" and r["phase"] == "rerun"]
    assert all(int(r["calls"]) == 0 for r in eco_l0), [(r["task"], r["calls"]) for r in eco_l0]
    assert all(r["success"] == "1" for r in eco_l0), [(r["task"], r["oracle"]) for r in eco_l0]
    noc = [r for r in rows if r["variant"] == "nocache" and r["phase"] == "rerun"]
    assert all(int(r["calls"]) > 0 for r in noc), "nocache must pay on every run"
    print("lab pipeline OK")
    shop_part(drift_bench)


def shop_part(drift_bench) -> None:
    """The same pipeline on the test shop (--site shop): one analysis task, levels baseline / markup refactor /
    data change. Skipped (with a message) when Node.js or test_shop/ is not available."""
    from ecogent import test_shop
    if not test_shop.available() or not test_shop.node():
        print("shop pipeline SKIPPED (Node.js or test_shop/ not found)")
        return
    out = SCRATCH / "shop.csv"
    out.unlink(missing_ok=True)
    sys.argv = ["drift_bench", "--site", "shop", "--tasks", "nw_kitchen_price_range", "--variants", "ecogent,nocache",
                "--levels", "0,2,8", "--seeds", "1", "--price", "fake=1,2", "--out", str(out), "--headless",
                "--debug-port", "9282"]
    drift_bench.main()
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == (1 + 3 * 2) + (1 + 3), len(rows)
    get = lambda v, lv, ph: next(r for r in rows if r["variant"] == v and r["level"] == lv and r["phase"] == ph)  # noqa: E731
    cold = get("ecogent", "0", "cold")
    assert int(cold["calls"]) > 0 and cold["success"] == "1", ("cold", cold["calls"], cold["oracle"])
    l0 = get("ecogent", "0", "rerun")
    assert int(l0["calls"]) == 0 and l0["success"] == "1", ("baseline rerun", l0["calls"], l0["oracle"])
    l2 = get("ecogent", "2", "rerun")
    assert l2["success"] == "1", ("markup-refactor rerun", l2["oracle"])
    l8 = get("ecogent", "8", "rerun")
    assert int(l8["calls"]) > 0, "data change: the analysis must be redone, not served from the cache"
    assert l8["success"] == "1", ("data-change rerun must report the NEW prices", l8["oracle"])
    assert all(int(r["calls"]) > 0 for r in rows if r["variant"] == "nocache"), "nocache must pay on every run"
    print("shop pipeline OK")
    print("FAKE RUN OK")


if __name__ == "__main__":
    main()
