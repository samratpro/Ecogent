"""
Real-world case study console: you drive each agent yourself on the cases in bench/real_cases.json
and judge the result with the case's written pass rule. Repeat the same cases each week (rounds):
real sites change by themselves, so later rounds measure natural drift.

    python bench/real_log.py --system ecogent --round 1
    python bench/real_log.py --system claude-in-chrome --round 1

Commands:
  cases                         list the cases
  start <id> [ecogent chat id]  print the prompt, start the timer; for Ecogent give the chat id
                                (shown in the chat folder name) so its tokens are measured
  score <1|0.5|0> [helps]       judge with the pass rule (0.5 = partly right); helps = times you had
                                to step in (captcha, login, answering a question)
  quit
Rows go to bench/results/real.csv: round, date, system, case, type, score, helps, seconds, and for
Ecogent the LLM calls / tokens used by that chat during the attempt.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIELDS = ["round", "date", "system", "case", "type", "site", "score", "helps", "seconds", "calls",
          "input_tokens", "output_tokens", "cached_input_tokens", "chat_id", "note"]


def chat_usage(home: Path, chat_id: str) -> dict:
    p = home / "chats" / chat_id / "chat.json"
    if not chat_id or not p.exists():
        return {}
    u = json.loads(p.read_text(encoding="utf-8")).get("usage", {})
    return {k: u.get(k, 0) for k in ("calls", "input_tokens", "output_tokens", "cached_input_tokens")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", required=True, help="agent name + version, e.g. ecogent or perplexity-comet-2026-11")
    ap.add_argument("--round", type=int, required=True, help="1 for week 1, 2 for week 2, ...")
    ap.add_argument("--cases", default=str(ROOT / "bench" / "real_cases.json"))
    ap.add_argument("--out", default=str(ROOT / "bench" / "results" / "real.csv"))
    args = ap.parse_args()
    cases = {c["id"]: c for c in json.loads(Path(args.cases).read_text(encoding="utf-8"))}
    from ecogent.config import Settings
    home = Path(Settings.load().home)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    new = not out.exists()
    cur, chat, t0, before = None, "", 0.0, {}
    print(f"{len(cases)} cases. Type 'cases', 'start <id> [chat id]', 'score <1|0.5|0> [helps]' or 'quit'.")
    with out.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        while True:
            try:
                parts = input("> ").strip().split()
            except EOFError:
                break
            if not parts:
                continue
            if parts[0] in ("quit", "exit"):
                break
            if parts[0] == "cases":
                for c in cases.values():
                    print(f"  {c['id']} [{c['type']}] {c['site']}: {c['prompt'][:80]}...")
            elif parts[0] == "start" and len(parts) > 1 and parts[1].upper() in cases:
                cur, chat = cases[parts[1].upper()], (parts[2] if len(parts) > 2 else "")
                before, t0 = chat_usage(home, chat), time.time()
                print(f"\nPrompt:\n  {cur['prompt']}\nPass rule: {cur['pass']}\n")
            elif parts[0] == "score" and cur and len(parts) > 1 and parts[1] in ("1", "0.5", "0"):
                after = chat_usage(home, chat)
                used = {k: after.get(k, 0) - before.get(k, 0) for k in after} if after else {}
                note = input("  note (optional): ").strip()
                w.writerow({"round": args.round, "date": datetime.now(timezone.utc).date().isoformat(),
                            "system": args.system, "case": cur["id"], "type": cur["type"], "site": cur["site"],
                            "score": parts[1], "helps": parts[2] if len(parts) > 2 else "0",
                            "seconds": round(time.time() - t0, 1), "chat_id": chat, "note": note, **used})
                fh.flush()
                print(f"  saved: {cur['id']} score {parts[1]}" + (f", {used.get('calls', 0)} LLM calls" if used else ""))
                cur = None
            else:
                print("  commands: cases | start <id> [chat id] | score <1|0.5|0> [helps] | quit")


if __name__ == "__main__":
    main()
