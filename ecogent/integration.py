"""
Using Ecogent from another agent or program (LLM tool call).

The caller must state the task type together with the intent. If the type is
missing or unknown, Ecogent classifies the request and reports what it chose.
"""

from __future__ import annotations

from typing import Optional

from .bridge import HeadlessBridge
from .config import NOT_IMPLEMENTED_TYPES, TASK_TYPES, Settings
from .core import EcogentAgent

TOOL_SCHEMA = {
    "name": "ecogent_browser_task",
    "description": ("Run a browser task with Ecogent (analysis, data scraping, automation). "
                    "Ecogent plans once, reuses cached plans and selectors on later runs, and writes the "
                    "result file to its output folder."),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_type": {"type": "string", "enum": [t for t in TASK_TYPES if t not in NOT_IMPLEMENTED_TYPES]},
            "intent": {"type": "string", "description": "One sentence: what the user wants and why."},
            "prompt": {"type": "string", "description": "The full task request."},
            "chat_id": {"type": "string", "description": "Continue an existing Ecogent chat (follow-up)."},
        },
        "required": ["task_type", "intent", "prompt"],
    },
}


def run_tool_call(args: dict, settings: Optional[Settings] = None, printer=print) -> dict:
    settings = settings or Settings.load()
    agent = EcogentAgent(settings, HeadlessBridge(printer))
    try:
        if args.get("chat_id"):
            chat_id = args["chat_id"]
            agent.handle_message(chat_id, args["prompt"])
        else:
            task_type = args.get("task_type")
            intent = args.get("intent", "")
            if task_type not in TASK_TYPES:
                guess = agent.classify(args["prompt"])
                task_type, intent = guess["task_type"], guess.get("intent", intent)
            s = agent.new_chat(task_type, headless=True)
            s.update_meta(intent=intent)
            chat_id = s.id
            agent.handle_message(chat_id, args["prompt"])
        s = agent.session(chat_id)
        return {
            "chat_id": chat_id,
            "task_type": s.meta.get("task_type"),
            "status": s.meta.get("status"),
            "output_file": s.plan.get("data", {}).get("output_file", ""),
            "reply": next((m["text"] for m in reversed(s.chat.get("messages", [])) if m["role"] == "agent"), ""),
            "usage": s.usage,
        }
    finally:
        agent.browser.close()
