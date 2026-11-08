"""
Manual benchmark console: serves the lab sites at a chosen drift level and scores attempts made by
any agent you drive by hand (Claude in Chrome, Perplexity Comet, Antigravity, browser-use, ...)
with the same oracles as drift_bench.py. Results go to a CSV (default bench/results/manual.csv).

    python -m bench.lab.serve --system "claude-in-chrome" --level 0 --seed 1

Commands at the prompt:
  tasks                    list task names and prompts
  start <task>             reset the site state, print the prompt to give the agent, start the timer
  score [output file]      score the current task (scraping/analysis need the agent's output file;
                           automation is scored from what the site recorded) and save a row
  level <n> / seed <n>     change drift level (0-4) / seed
  quit
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

from . import drift
from .server import LabServer
from .tasks import BY_NAME, TASKS, USER_INFO

FIELDS = ["system", "task", "type", "level", "seed", "success", "precision", "recall", "oracle", "seconds",
          "note", "time"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", required=True, help="name of the agent you are testing")
    ap.add_argument("--level", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--out", default="bench/results/manual.csv")
    args = ap.parse_args()
    srv = LabServer(port=args.port)
    srv.set(args.level, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    new = not out.exists()
    current, t0 = None, 0.0
    print(f"Lab running at {srv.base}  (level {args.level} = {drift.LEVELS[args.level]}, seed {args.seed})")
    print("Type 'tasks', 'start <task>', 'score [file]', 'level <n>', 'seed <n>' or 'quit'.")
    try:
        with out.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                w.writeheader()
            while True:
                try:
                    cmd = input("> ").strip()
                except EOFError:
                    break
                word, _, rest = cmd.partition(" ")
                rest = rest.strip().strip('"')
                if word in ("quit", "exit"):
                    break
                if word == "tasks":
                    for t in TASKS:
                        print(f"  {t.name:<24} [{t.type}] {t.prompt.format(base=srv.base)[:90]}...")
                elif word in ("level", "seed") and rest.isdigit():
                    if word == "level":
                        args.level = int(rest)
                    else:
                        args.seed = int(rest)
                    srv.set(args.level, args.seed)
                    print(f"  now level {args.level} ({drift.LEVELS.get(args.level, '?')}), seed {args.seed}")
                elif word == "start" and rest in BY_NAME:
                    current, t0 = BY_NAME[rest], time.time()
                    srv.reset()
                    prompt = current.prompt.format(base=srv.base)
                    if "my full name" in prompt:     # Ecogent gets these from its user-info file
                        prompt += f" My full name is {USER_INFO['full_name']} and my email is {USER_INFO['email']}."
                    print("\nGive the agent exactly this prompt:\n")
                    print("  " + prompt + "\n")
                elif word == "score" and current:
                    output = Path(rest) if rest else None
                    if current.type in ("scraping", "analysis") and not output:
                        print("  this task needs the agent's output file: score <path>")
                        continue
                    v = current.oracle(output, srv.state)
                    note = input("  note (optional): ").strip()
                    w.writerow({"system": args.system, "task": current.name, "type": current.type,
                                "level": args.level, "seed": args.seed, "success": int(v["success"]),
                                "precision": v["precision"], "recall": v["recall"], "oracle": v["detail"],
                                "seconds": round(time.time() - t0, 1), "note": note,
                                "time": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                    fh.flush()
                    print(f"  success={v['success']} precision={v['precision']} recall={v['recall']} ({v['detail']})")
                else:
                    print("  commands: tasks | start <task> | score [file] | level <n> | seed <n> | quit")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
