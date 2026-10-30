"""
python -m ecogent                      -> desktop GUI
python -m ecogent --type analysis "..." -> headless run (prints result JSON)
"""

import argparse
import json
import sys

from .config import TASK_TYPES


def main() -> None:
    ap = argparse.ArgumentParser(prog="ecogent")
    ap.add_argument("prompt", nargs="?", help="run headless with this task prompt (omit for the GUI)")
    ap.add_argument("--type", choices=TASK_TYPES, help="task type (auto-detected when omitted)")
    ap.add_argument("--intent", default="", help="one-sentence intent (for tool calls)")
    ap.add_argument("--chat", help="continue an existing chat id")
    args = ap.parse_args()
    if not args.prompt:
        from .gui.app import main as gui_main
        gui_main()
        return
    from .integration import run_tool_call
    result = run_tool_call({"task_type": args.type, "intent": args.intent, "prompt": args.prompt, "chat_id": args.chat},
                           printer=lambda t: print(t, file=sys.stderr))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
