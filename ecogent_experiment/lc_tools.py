"""
LangChain Tool Wrappers for Ecogent.

Wraps every function in tools/builtin/*.py as a LangChain BaseTool.
The agent uses tool descriptions to decide which to call — no hardcoded routing.

Design:
- Each tool accepts a single JSON string input (LangChain standard)
- ask_llm is injected at runtime via EcogentToolContext
- Returns a plain string so the agent can read the Observation clearly
- Tools are grouped by category for selective loading
"""

import json
import sys
import os
from typing import Any, Callable, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

# Ensure project root is on path so tools.builtin.* imports work
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Shared input schema — all tools accept a flat JSON string
# ---------------------------------------------------------------------------

class JSONInput(BaseModel):
    input: str = Field(description="JSON string with tool parameters")


# ---------------------------------------------------------------------------
# Base wrapper
# ---------------------------------------------------------------------------

class EcogentTool(BaseTool):
    """
    Base class for all Ecogent tools.
    Parses JSON input, calls the underlying function, returns string result.
    """
    name: str
    description: str
    func: Any = Field(exclude=True, default=None)
    ask_llm: Any = Field(exclude=True, default=None)  # injected at runtime
    args_schema: Type[BaseModel] = JSONInput

    class Config:
        arbitrary_types_allowed = True

    def _run(self, input: str) -> str:
        input_str = input.strip()
        if input_str.startswith("{"):
            try:
                kwargs = json.loads(input_str)
            except json.JSONDecodeError as e:
                return f"JSON Parse Error: Your Action Input must be valid JSON. Ensure proper quotes and do not use unescaped line breaks inside strings. Error details: {e}"
        else:
            kwargs = {"task": input_str}

        if self.ask_llm:
            kwargs["ask_llm"] = self.ask_llm

        try:
            result = self.func(**kwargs)
            if isinstance(result, dict):
                # Return a readable summary, not raw dict
                if result.get("success") is False:
                    err_msg = result.get('error') or result.get('stderr') or 'Unknown error'
                    return f"ERROR: {err_msg}"
                if "preview" in result:
                    return result["preview"]
                if "content" in result:
                    return str(result["content"])[:2000]
                return json.dumps(result, ensure_ascii=False)
            return str(result)[:3000]
        except Exception as e:
            return f"Tool error ({self.name}): {e}"

    async def _arun(self, input: str) -> str:
        return self._run(input)


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def _make_tool(name: str, description: str, func: Callable) -> EcogentTool:
    return EcogentTool(name=name, description=description, func=func)


# ---------------------------------------------------------------------------
# Tool definitions — grouped by category
# ---------------------------------------------------------------------------

def get_web_tools(ask_llm: Optional[Callable] = None) -> list[EcogentTool]:
    from tools.builtin.web import web_search, browse_website
    tools = [
        _make_tool(
            "web_search",
            "Search the web (Bing by default). Input: {query, engine(optional)}. "
            "Use for: finding information online, searching any topic, Bing/Google searches.",
            web_search,
        ),
        _make_tool(
            "browse_website",
            "Fetch and read a website's content. Input: {url}. "
            "Use for: opening a URL, reading a webpage, scraping a site.",
            browse_website,
        ),
    ]
    for t in tools:
        t.ask_llm = ask_llm
    return tools


def get_browser_automation_tools() -> list[EcogentTool]:
    """Pattern-based Playwright browser automation tool."""
    from tools.builtin.browser_automation import browser_task
    return [
        _make_tool(
            "browser_task",
            (
                "Execute a multi-step browser automation task using Playwright. "
                "Automatically records a reusable workflow pattern on first run "
                "(communicating step-by-step with AI) and replays it with ZERO AI calls "
                "on subsequent runs. Use for: 'go to amazon and check laptop prices', "
                "'fill out a web form', 'compare products across pages', "
                "'navigate and extract data from any website'. "
                "Input: {task, project_id, variables(optional)}"
            ),
            browser_task,
        ),
    ]


def get_filesystem_tools() -> list[EcogentTool]:
    from tools.builtin.filesystem import (
        read_file, write_file, list_directory,
        create_directory, delete_file, copy_file,
        move_file, search_files, file_exists,
    )
    return [
        _make_tool("read_file", "Read contents of a file. Input: {path}", read_file),
        _make_tool("write_file", "Write text to a file. Input: {path, content}", write_file),
        _make_tool("list_directory", "List files in a directory. Input: {path}", list_directory),
        _make_tool("create_directory", "Create a new directory. Input: {path}", create_directory),
        _make_tool("delete_file", "Delete a file. Input: {path}", delete_file),
        _make_tool("copy_file", "Copy a file. Input: {source, destination}", copy_file),
        _make_tool("move_file", "Move or rename a file. Input: {source, destination}", move_file),
        _make_tool("search_files", "Search files by pattern. Input: {directory, pattern}", search_files),
        _make_tool("file_exists", "Check if a file exists. Input: {path}", file_exists),
    ]


def get_data_tools() -> list[EcogentTool]:
    from tools.builtin.data import (
        read_csv, inspect_csv, filter_dataframe,
        calculate_statistics, save_csv,
    )
    return [
        _make_tool("read_csv", "Read a CSV file. Input: {path}", read_csv),
        _make_tool("inspect_csv", "Inspect CSV schema and columns. Input: {path}", inspect_csv),
        _make_tool("filter_dataframe", "Filter CSV rows. Input: {path, column, value}", filter_dataframe),
        _make_tool("calculate_statistics", "Calculate stats on CSV. Input: {path, column(optional)}", calculate_statistics),
        _make_tool("save_csv", "Save data to CSV. Input: {data, path}", save_csv),
    ]


def get_system_tools() -> list[EcogentTool]:
    from tools.builtin.system import system_info, process_info
    return [
        _make_tool("system_info", "Get system hardware/OS info. Input: {}", system_info),
        _make_tool("process_info", "List running processes. Input: {}", process_info),
    ]


def get_shell_tools() -> list[EcogentTool]:
    from tools.builtin.shell import run_shell_command
    return [
        _make_tool(
            "run_shell",
            "Run a shell command and return output. Input: {command}. "
            "Use for: running scripts, CLI tools, pip installs, etc.",
            run_shell_command,
        ),
    ]


def get_network_tools() -> list[EcogentTool]:
    from tools.builtin.network import ping_host, check_port_open
    return [
        _make_tool("ping_host", "Ping a host to check connectivity. Input: {host}", ping_host),
        _make_tool("check_port_open", "Check if a TCP port is open on a host. Input: {host, port}", check_port_open),
    ]


def get_git_tools() -> list[EcogentTool]:
    from tools.builtin.git import git_status, git_commit, git_diff
    return [
        _make_tool("git_status", "Get git repository status. Input: {path(optional)}", git_status),
        _make_tool("git_commit", "Commit staged changes. Input: {message, path(optional)}", git_commit),
        _make_tool("git_diff", "Show git diff. Input: {path(optional)}", git_diff),
    ]


def get_testing_tools() -> list[EcogentTool]:
    from tools.builtin.testing import run_python_test
    return [
        _make_tool(
            "run_python_test",
            "Run pytest tests. Input: {path, test_file(optional)}",
            run_python_test,
        ),
    ]


def get_code_tools() -> list[EcogentTool]:
    from tools.builtin.shell import run_shell_command

    def run_python_inline(code: str = "", task: str = "", **kwargs) -> str:
        """Execute a Python code string inline and return output."""
        src = code or task
        if not src:
            return "No code provided."
        ns: dict = {}
        import io, contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(compile(src, "<inline>", "exec"), ns)  # noqa: S102
            return buf.getvalue() or "Executed successfully (no output)."
        except Exception as e:
            return f"Execution error: {e}"

    return [
        _make_tool(
            "run_python_inline",
            "Execute a Python code snippet inline. Input: {code}. "
            "Use for: quick calculations, data transforms, scripting without a file.",
            run_python_inline,
        ),
    ]


# ---------------------------------------------------------------------------
# Master loader
# ---------------------------------------------------------------------------

def get_all_tools(ask_llm: Optional[Callable] = None) -> list[EcogentTool]:
    """
    Load and return all builtin LangChain tools.
    ask_llm is injected into web tools for intelligent intent parsing.
    """
    tools: list[EcogentTool] = []

    loaders = [
        (get_web_tools, {"ask_llm": ask_llm}),
        (get_browser_automation_tools, {}),
        (get_filesystem_tools, {}),
        (get_data_tools, {}),
        (get_system_tools, {}),
        (get_shell_tools, {}),
        (get_network_tools, {}),
        (get_git_tools, {}),
        (get_testing_tools, {}),
        (get_code_tools, {}),
    ]

    for loader, kwargs in loaders:
        try:
            tools.extend(loader(**kwargs))
        except Exception as e:
            # Don't crash if an optional module is missing
            import warnings
            warnings.warn(f"Could not load tools from {loader.__name__}: {e}")

    return tools


def get_tool_descriptions(tools: list[EcogentTool]) -> list[dict]:
    """Return tool metadata dicts compatible with ToolRegistry format."""
    _browser_agent_tools = {"web_search", "browse_website", "browser_task"}
    return [
        {
            "tool_key": t.name,
            "natural_name": t.name.replace("_", " ").title(),
            "description": t.description,
            "agent": "browser_agent" if t.name in _browser_agent_tools else "os_agent",
            "category": "builtin",
        }
        for t in tools
    ]
