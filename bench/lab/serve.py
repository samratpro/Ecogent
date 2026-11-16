"""
Manual benchmark console: serves the lab sites (or switches the test shop) at a chosen level and scores
attempts made by any agent you drive by hand (Claude in Chrome, Perplexity Comet, Antigravity, ...)
with the same oracles as drift_bench.py. Results go to a CSV (default bench/results/manual.csv).

    python -m bench.lab.serve --system "claude-in-chrome-2026-11" --level 0 --seed 1
    python -m bench.lab.serve --site shop --system "perplexity-comet-2026-11" --level 0

--site lab   the lab sites, drift levels 0-4 (served by this console on --port)
--site shop  the test shop on http://localhost:3010 (started if needed), levels 0-9 = one change each

Commands at the prompt:
  tasks                    list task names and prompts
  start <task>             reset the site state, print the prompt to give the agent, start the timer
  score [output file]      score the current task with the agent's output file (scraping / analysis);
                           automation is scored from what the site recorded
  paste                    paste the agent's answer from its chat window (end with a line: END); it is
                           saved next to the CSV and scored like a file
  level <n> / seed <n>     change level / seed
  quit
Each score asks how many times you had to step in ("helps") and for an optional note.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import drift
from .tasks import USER_INFO

FIELDS = ["system", "site", "task", "type", "level", "level_name", "seed", "success", "precision", "recall", "oracle",
          "seconds", "helps", "note", "time"]


def _site(name: str, port: int):
    """(target, tasks, by_name, level names) for the chosen site."""
    if name == "shop":
        from bench import shop_tasks
        return shop_tasks.ShopTarget(), shop_tasks.TASKS, shop_tasks.BY_NAME, shop_tasks.LEVELS
    from .server import LabServer
    from .tasks import BY_NAME, TASKS
    return LabServer(port=port), TASKS, BY_NAME, drift.LEVELS


def _paste(folder: Path, task: str) -> Path | None:
    print("  Paste the agent's answer, then a line with only END:")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    if not text:
        return None
    looks_csv = sum(1 for l in lines if l.count(",") >= 1) >= max(2, len(lines) // 2)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{task}_{datetime.now():%Y%m%d_%H%M%S}.{'csv' if looks_csv else 'md'}"
    out.write_text(text + "\n", encoding="utf-8")
    print(f"  saved as {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", required=True, help="name and version of the agent you are testing")
    ap.add_argument("--site", choices=["lab", "shop"], default="lab")
    ap.add_argument("--level", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--port", type=int, default=8790, help="lab only")
    ap.add_argument("--out", default="bench/results/manual.csv")
    args = ap.parse_args()
    srv, tasks, by_name, levels = _site(args.site, args.port)
    if args.level not in levels:
        sys.exit(f"--level must be one of {sorted(levels)} for --site {args.site}")
    srv.set(args.level, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    answers = out.parent / "manual_answers"
    new = not out.exists()
    if not new:
        with out.open(encoding="utf-8") as f:
            header = next(csv.reader(f), [])
        if header != FIELDS:
            sys.exit(f"{out} has other columns (an older console). Use --out with a new file name.")
    current, t0 = None, 0.0
    print(f"{args.site} running at {srv.base}  (level {args.level} = {levels[args.level]}, seed {args.seed})")
    print("Type 'tasks', 'start <task>', 'score [file]', 'paste', 'level <n>', 'seed <n>' or 'quit'.")
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
                    for t in tasks:
                        print(f"  {t.name:<24} [{t.type}] {t.prompt.format(base=srv.base)[:90]}...")
                elif word in ("level", "seed") and rest.isdigit():
                    if word == "level" and int(rest) not in levels:
                        print(f"  levels: {', '.join(f'{k}={v}' for k, v in levels.items())}")
                        continue
                    if word == "level":
                        args.level = int(rest)
                    else:
                        args.seed = int(rest)
                    srv.set(args.level, args.seed)
                    print(f"  now level {args.level} ({levels[args.level]}), seed {args.seed}")
                elif word == "start" and rest in by_name:
                    current, t0 = by_name[rest], time.time()
                    srv.reset()
                    prompt = current.prompt.format(base=srv.base)
                    if "my full name" in prompt:     # Ecogent gets these from its user-info file
                        prompt += f" My full name is {USER_INFO['full_name']} and my email is {USER_INFO['email']}."
                    print("\nGive the agent exactly this prompt (fresh chat, one attempt, do not help it):\n")
                    print("  " + prompt + "\n")
                elif word in ("score", "paste") and current:
                    seconds = round(time.time() - t0, 1)
                    output = _paste(answers, current.name) if word == "paste" else (Path(rest) if rest else None)
                    if current.type in ("scraping", "analysis") and not output:
                        print("  this task needs the agent's answer: score <file> or paste")
                        continue
                    v = current.oracle(output, srv.state)
                    helps = input("  how many times did you step in? [0]: ").strip()
                    note = input("  note (optional): ").strip()
                    w.writerow({"system": args.system, "site": args.site, "task": current.name, "type": current.type,
                                "level": args.level, "level_name": levels[args.level], "seed": args.seed,
                                "success": int(v["success"]), "precision": v["precision"], "recall": v["recall"],
                                "oracle": v["detail"], "seconds": seconds,
                                "helps": int(helps) if re.fullmatch(r"\d+", helps) else 0, "note": note,
                                "time": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                    fh.flush()
                    print(f"  success={v['success']} precision={v['precision']} recall={v['recall']} ({v['detail']})")
                else:
                    print("  commands: tasks | start <task> | score [file] | paste | level <n> | seed <n> | quit")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
