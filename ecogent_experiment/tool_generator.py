"""
Tool Generator.

Uses cloud LLMs to generate new local tools on-demand.

Key improvements:
- Detects task intent to assign the correct agent (browser_agent vs os_agent)
- Sends prebuild + project tool context so LLM can return USE_EXISTING:<key>
  instead of generating duplicate code (saves tokens per spec point iv)
- Saves generated .py files with the project root in sys.path so exec() works
- Returns the absolute file_path in the tool_spec for direct exec() fallback
"""

import os
import re
import sys
import ast
from typing import Optional

from ecogent_experiment.providers.cloud import CloudLLMProvider


# ---------------------------------------------------------------------------
# Intent detection helpers
# ---------------------------------------------------------------------------

_BROWSER_PATTERNS = re.compile(
    r"\b(browse|web|search|google|bing|duckduckgo|scrape|crawl|"
    r"navigate|visit|open\s+(url|site|page)|http|www\.|download\s+from|"
    r"internet|online)\b",
    re.I,
)

_AGENT_FOR_CATEGORY = {
    "browser": "browser_agent",
    "web": "browser_agent",
    "search": "browser_agent",
    "filesystem": "os_agent",
    "data": "os_agent",
    "system": "os_agent",
    "code": "os_agent",
    "testing": "os_agent",
}


def _detect_agent(task: str) -> str:
    """Return the most appropriate agent for a task description."""
    if _BROWSER_PATTERNS.search(task):
        return "browser_agent"
    return "os_agent"


# ---------------------------------------------------------------------------
# ToolGenerator
# ---------------------------------------------------------------------------

class ToolGenerator:
    """
    Generates deterministic Python tools dynamically using a cloud provider,
    registering them for future local execution to save costs.

    If the cloud LLM determines that an existing tool already covers the task,
    it returns ``USE_EXISTING:<tool_key>`` and no new code is generated.
    """

    def __init__(
        self,
        cloud_provider: CloudLLMProvider,
        tool_registry=None,
        project_id: str = None,
        project_root: str = None,
    ):
        self.cloud_provider = cloud_provider
        self.tool_registry = tool_registry
        self.project_id = project_id
        # Resolve project root so generated tools land in the right place
        self.project_root = project_root or self._guess_project_root()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _guess_project_root() -> str:
        """Walk up from this file to find the project root (contains config/)."""
        current = os.path.dirname(os.path.abspath(__file__))
        for _ in range(4):
            candidate = os.path.dirname(current)
            if os.path.isdir(os.path.join(candidate, "config")):
                return candidate
            current = candidate
        return os.path.dirname(os.path.abspath(__file__))

    def _tools_dir(self) -> str:
        """Return the absolute path to the tools output directory."""
        if self.project_id:
            path = os.path.join(self.project_root, "projects", self.project_id, "tools")
        else:
            path = os.path.join(self.project_root, "tools", "generated")
        os.makedirs(path, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_tool(
        self,
        task: str,
        existing_tools_ctx: Optional[list] = None,
        step_n: int = 1,
    ) -> tuple:
        """
        Generate (or reuse) a tool for the given task.

        Returns:
            (tool_spec_dict | None, input_tokens: int, output_tokens: int)

        tool_spec_dict contains:
            tool_key, natural_name, description, category, agent,
            code, project_id, file_path
        """
        # Build context strings for the prompt
        context_str = ""
        if existing_tools_ctx:
            context_str = (
                "\n\nExisting tools (DO NOT duplicate — "
                "if one of these already handles the task, reply with exactly: "
                "USE_EXISTING:<tool_key>):\n"
                + "\n".join(existing_tools_ctx)
                + "\n"
            )

        # Detect appropriate agent
        agent = _detect_agent(task)

        # Build the generation prompt
        agent_hint = (
            "The tool will run inside a **browser_agent** context. "
            "You may use urllib, requests, or playwright (prefer urllib for portability). "
            "For web search tasks use the Bing URL: https://www.bing.com/search?q=<query>."
            if agent == "browser_agent"
            else "The tool will run inside an **os_agent** context. "
            "Use standard library or commonly available packages."
        )

        prompt = (
            f"Write a pure Python function to solve this task:\n"
            f"Task: {task}\n"
            f"Step number: {step_n} in the workflow.\n"
            f"{agent_hint}\n"
            f"{context_str}\n"
            "Rules:\n"
            "- If an EXISTING tool already covers this task, reply ONLY with: USE_EXISTING:<tool_key>\n"
            "- Otherwise respond ONLY with valid Python code in a ```python block.\n"
            "- The function must be self-contained and stateless.\n"
            "- Accept **kwargs as the last parameter.\n"
            "- If you need to query the LLM during execution, call: kwargs.get('ask_llm')('your prompt')\n"
            "- Return a dict or string result.\n"
            "- Do NOT include if __name__ == '__main__' blocks.\n"
        )

        result = self.cloud_provider.generate_plan(prompt)
        answer = result.get("answer", "").strip()
        in_tok = result.get("input_tokens", 0)
        out_tok = result.get("output_tokens", 0)

        # --- Check for USE_EXISTING signal ---
        use_existing_match = re.match(r"USE_EXISTING[:\s]+(\S+)", answer, re.I)
        if use_existing_match:
            existing_key = use_existing_match.group(1).strip().strip(":").strip()
            # Try to look it up in the registry and return it
            if self.tool_registry:
                for coll in ("builtin_tools", "project_tools", "generated_tools"):
                    tool = self.tool_registry.get_tool(existing_key, coll)
                    if tool:
                        tool["reused"] = True
                        return tool, in_tok, out_tok
            # Return a minimal stub so the caller still gets a valid spec
            return {
                "tool_key": existing_key,
                "natural_name": existing_key,
                "description": task,
                "category": "reused",
                "agent": agent,
                "code": None,
                "file_path": None,
                "project_id": self.project_id,
                "reused": True,
            }, in_tok, out_tok

        # --- Extract python code block ---
        tool_code = ""
        if "```python" in answer:
            tool_code = answer.split("```python", 1)[1].split("```", 1)[0].strip()
        elif "```" in answer:
            tool_code = answer.split("```", 1)[1].split("```", 1)[0].strip()
        else:
            tool_code = answer

        if not tool_code:
            return None, in_tok, out_tok

        # Validate syntax
        try:
            ast.parse(tool_code)
        except SyntaxError:
            return None, in_tok, out_tok

        # Build a deterministic but human-readable tool key
        safe_slug = re.sub(r"[^a-z0-9_]", "_", task.lower())[:40].strip("_")
        tool_key = f"gen_{safe_slug}_{abs(hash(task)) % 100000}"

        # Save to filesystem
        tools_dir = self._tools_dir()
        file_path = os.path.join(tools_dir, f"{tool_key}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(tool_code)

        # Ensure an __init__.py exists in the directory so the module is importable
        init_path = os.path.join(tools_dir, "__init__.py")
        if not os.path.exists(init_path):
            open(init_path, "w").close()

        # Also ensure project root is on sys.path for importlib
        if self.project_root not in sys.path:
            sys.path.insert(0, self.project_root)

        tool_spec = {
            "tool_key": tool_key,
            "natural_name": f"Generated: {task[:60]}",
            "description": task,
            "category": "browser" if agent == "browser_agent" else "generated",
            "agent": agent,
            "code": tool_code,
            "file_path": file_path,
            "project_id": self.project_id,
        }

        if self.tool_registry:
            self.tool_registry.register_tool(
                tool_key=tool_spec["tool_key"],
                natural_name=tool_spec["natural_name"],
                description=tool_spec["description"],
                category=tool_spec["category"],
                agent=tool_spec["agent"],
                persistent=False,
                collection="project_tools" if self.project_id else "generated_tools",
                extra_metadata={
                    "project_id": self.project_id or "",
                    "file_path": file_path,
                },
            )

        return tool_spec, in_tok, out_tok
