"""
JSON Context Manager for Ecogent.

Builds minimal per-step context packets so the agent never receives
the full chat history or plan — only what it needs for the current step.

Token budget per packet (approximate):
  - step goal:        ~50 tokens
  - available tools:  ~80 tokens  (names + 1-line descriptions)
  - past results:     ~150 tokens (truncated summaries)
  - system header:    ~30 tokens
  Total target:       < 400 tokens of injected context per step
"""

import json
from typing import Any, Optional


# Max chars for each past step result before truncation
_RESULT_TRUNCATE = 300
# Max chars for tool description in the context packet
_TOOL_DESC_TRUNCATE = 80


class ContextPacket:
    """
    A minimal, serializable context object passed to the agent per step.

    Only contains what this specific step needs — nothing more.
    """

    def __init__(
        self,
        user_task: str,
        step_n: int,
        total_steps: int,
        step_goal: str,
        available_tools: list[dict],      # [{tool_key, description, agent}]
        past_results: dict[str, str],     # {step_goal: result_summary}
        project_id: Optional[str] = None,
        workspace_dir: Optional[str] = None,
    ):
        self.user_task = user_task
        self.step_n = step_n
        self.total_steps = total_steps
        self.step_goal = step_goal
        self.available_tools = available_tools
        self.past_results = past_results
        self.project_id = project_id
        self.workspace_dir = workspace_dir

    def to_json(self) -> str:
        """Serialize to compact JSON string for LLM injection."""
        tools_summary = [
            {
                "tool": t.get("tool_key", ""),
                "desc": t.get("description", "")[:_TOOL_DESC_TRUNCATE],
                "agent": t.get("agent", "os_agent"),
            }
            for t in self.available_tools[:12]  # cap at 12 tools
        ]

        truncated_past = {
            goal: (result[:_RESULT_TRUNCATE] + "..." if len(result) > _RESULT_TRUNCATE else result)
            for goal, result in self.past_results.items()
        }

        packet = {
            "user_task": self.user_task,
            "step": self.step_n,
            "total_steps": self.total_steps,
            "step_goal": self.step_goal,
            "available_tools": tools_summary,
            "past_step_results": truncated_past,
        }
        if self.project_id:
            packet["project_id"] = self.project_id

        return json.dumps(packet, ensure_ascii=False, separators=(",", ":"))

    def to_prompt_str(self) -> str:
        """Format as a clean prompt section for injection into the agent system prompt."""
        lines = [
            f"## Current Task Context",
            f"User request: {self.user_task}",
            f"Current step: {self.step_n} of {self.total_steps}",
            f"Step goal: {self.step_goal}",
        ]
        if self.workspace_dir:
            lines.append(f"Workspace directory: {self.workspace_dir}")

        if self.available_tools:
            lines.append("\nAvailable tools:")
            for t in self.available_tools[:12]:
                desc = t.get("description", "")[:_TOOL_DESC_TRUNCATE]
                lines.append(f"  - {t.get('tool_key')}: {desc}")

        if self.past_results:
            lines.append("\nCompleted steps so far:")
            for goal, result in self.past_results.items():
                r = result[:_RESULT_TRUNCATE] + ("..." if len(result) > _RESULT_TRUNCATE else "")
                lines.append(f"  [{goal}] → {r}")

        return "\n".join(lines)


class ContextManager:
    """
    Builds ContextPackets for each step in the workflow.

    Tracks step results as they accumulate so each packet
    only carries the *previous* steps' summaries.
    """

    def __init__(self, user_task: str, project_id: Optional[str] = None, workspace_dir: Optional[str] = None):
        self.user_task = user_task
        self.project_id = project_id
        self.workspace_dir = workspace_dir
        # Maps step_goal -> result string (filled as steps complete)
        self._results: dict[str, str] = {}

    def record_result(self, step_goal: str, result: Any) -> None:
        """Record the result of a completed step."""
        self._results[step_goal] = str(result)[:_RESULT_TRUNCATE * 2]

    def build_packet(
        self,
        step_n: int,
        total_steps: int,
        step_goal: str,
        available_tools: list[dict],
    ) -> ContextPacket:
        """Build a minimal context packet for the current step."""
        return ContextPacket(
            user_task=self.user_task,
            step_n=step_n,
            total_steps=total_steps,
            step_goal=step_goal,
            available_tools=available_tools,
            past_results=dict(self._results),  # snapshot of results so far
            project_id=self.project_id,
            workspace_dir=self.workspace_dir,
        )

    def get_results_summary(self, max_chars_per_step: int = _RESULT_TRUNCATE) -> str:
        """Return all results as a compact string for the final verification step."""
        lines = []
        for goal, result in self._results.items():
            r = result[:max_chars_per_step] + ("..." if len(result) > max_chars_per_step else "")
            lines.append(f"- {goal}:\n  {r}")
        return "\n".join(lines)
