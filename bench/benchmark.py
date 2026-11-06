"""
Token / dollar cost benchmark for Ecogent (real LLM from your Settings, headless browser).

For every task it runs the task N times and records, per run: LLM calls and tokens by purpose,
cached input tokens, cost in USD, status and the executor's cache statistics.

Two modes:
  cached   (default) run 1 plans the task, runs 2..N use "Run again" (Ecogent's normal reuse)
  nocache  every run is a brand-new chat with plan memory off: the "no reuse" baseline
           (the ablation to compare against)

Usage (from the repo root):
  python bench/benchmark.py --tasks bench/tasks.example.json --runs 5 --mode cached \
      --price-in 0.15 --price-out 0.60 --price-cached 0.075 --out bench/results.csv
  python bench/benchmark.py ... --mode nocache        (append to the same CSV to compare)

Prices are USD per 1M tokens for your model. Tasks that need a human (login, captcha) are
reported as failed: headless runs never wait for a person.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecogent.bridge import HeadlessBridge          # noqa: E402
from ecogent.config import Settings, TASK_TYPES    # noqa: E402
from ecogent.core import EcogentAgent              # noqa: E402

FIELDS = ["task", "type", "mode", "run", "status", "seconds", "calls", "input_tokens", "cached_input_tokens",
          "output_tokens", "cost_usd", "cumulative_cost_usd", "by_purpose", "cache_hits", "local_heals",
          "local_picks", "llm_lookups", "healed", "steps_ok", "steps_failed", "chat_id"]


def usage_snapshot(session) -> dict:
    u = session.usage or {}
    return {"calls": u.get("calls", 0), "input_tokens": u.get("input_tokens", 0),
            "cached_input_tokens": u.get("cached_input_tokens", 0), "output_tokens": u.get("output_tokens", 0),
            "by_purpose": json.loads(json.dumps(u.get("by_purpose", {})))}


def usage_delta(before: dict, after: dict) -> dict:
    d = {k: after[k] - before[k] for k in ("calls", "input_tokens", "cached_input_tokens", "output_tokens")}
    purposes = {}
    for p, a in after["by_purpose"].items():
        b = before["by_purpose"].get(p, {})
        calls = a.get("calls", 0) - b.get("calls", 0)
        if calls:
            purposes[p] = {"calls": calls,
                           "in": a.get("input_tokens", 0) - b.get("input_tokens", 0),
                           "out": a.get("output_tokens", 0) - b.get("output_tokens", 0)}
    d["by_purpose"] = purposes
    return d


def cost(d: dict, p_in: float, p_out: float, p_cached: float) -> float:
    fresh = d["input_tokens"] - d["cached_input_tokens"]
    return (fresh * p_in + d["cached_input_tokens"] * p_cached + d["output_tokens"] * p_out) / 1_000_000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", required=True, help='JSON list: [{"name", "type", "prompt"}]')
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--mode", choices=["cached", "nocache"], default="cached")
    ap.add_argument("--price-in", type=float, required=True, help="USD per 1M input tokens")
    ap.add_argument("--price-out", type=float, required=True, help="USD per 1M output tokens")
    ap.add_argument("--price-cached", type=float, default=None, help="USD per 1M cached input tokens (default: price-in)")
    ap.add_argument("--out", default="bench/results.csv")
    ap.add_argument("--home", default="", help="data folder for benchmark chats (default: ecogent_data/bench)")
    args = ap.parse_args()
    p_cached = args.price_in if args.price_cached is None else args.price_cached

    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    settings = Settings.load()
    if not settings.main_llm.enabled:
        sys.exit("Configure the main LLM in the app's Settings first.")
    settings.home = args.home or str(Path(settings.home) / "bench")
    settings.headless = True
    settings.use_vector_memory = args.mode == "cached" and settings.use_vector_memory
    settings.ensure_dirs()
    agent = EcogentAgent(settings, HeadlessBridge(lambda t: print("  |", t, file=sys.stderr)))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    try:
        with out.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            for task in tasks:
                ttype = task.get("type", "others")
                if ttype not in TASK_TYPES:
                    print(f"skip {task.get('name')}: unknown type {ttype}", file=sys.stderr)
                    continue
                chat_id, total = None, 0.0
                for run in range(1, args.runs + 1):
                    fresh_chat = chat_id is None or args.mode == "nocache"
                    if fresh_chat:
                        if args.mode == "nocache":
                            agent.memory.index_file.unlink(missing_ok=True)   # no plan reuse across chats
                        chat_id = agent.new_chat(ttype, title=task.get("name", ""), headless=True).id
                    s = agent.session(chat_id)
                    before = usage_snapshot(s)
                    t0 = time.time()
                    if fresh_chat:
                        agent.handle_message(chat_id, task["prompt"])
                    else:
                        agent.rerun(chat_id)
                    s = agent.session(chat_id)
                    d = usage_delta(before, usage_snapshot(s))
                    c = cost(d, args.price_in, args.price_out, p_cached)
                    total += c
                    stats = (s.plan.get("runs") or [{}])[-1].get("stats", {})
                    row = {"task": task.get("name", ""), "type": ttype, "mode": args.mode, "run": run,
                           "status": s.meta.get("status"), "seconds": round(time.time() - t0, 1),
                           "calls": d["calls"], "input_tokens": d["input_tokens"],
                           "cached_input_tokens": d["cached_input_tokens"], "output_tokens": d["output_tokens"],
                           "cost_usd": round(c, 6), "cumulative_cost_usd": round(total, 6),
                           "by_purpose": json.dumps(d["by_purpose"]), "chat_id": chat_id,
                           **{k: stats.get(k, 0) for k in ("cache_hits", "local_heals", "local_picks", "llm_lookups",
                                                            "healed", "steps_ok", "steps_failed")}}
                    w.writerow(row)
                    f.flush()
                    print(f"{row['task']:<28} {args.mode:<7} run {run}: {row['status']:<8} calls {d['calls']:>3}  "
                          f"tokens {d['input_tokens']:>7} in / {d['output_tokens']:>6} out  ${c:.5f}  "
                          f"(total ${total:.5f})")
    finally:
        agent.browser.close()
    print(f"\nResults appended to {out}")


if __name__ == "__main__":
    main()
