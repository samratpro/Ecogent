"""
OS Agent. Handles filesystem, data, and system operations.
"""

import importlib
import os
import sys
from typing import Any

from ecogent_experiment.agents import BaseAgent


def _exec_tool_file(file_path: str, tool_key: str, **kwargs) -> Any:
    """
    Load a tool from an absolute .py file path using exec(),
    find the first callable (excluding builtins) and call it with kwargs.
    Returns the result or raises an exception.
    """
    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError(f"Tool file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()

    namespace: dict = {}
    exec(compile(code, file_path, "exec"), namespace)  # noqa: S102

    # Prefer exact name match
    func = namespace.get(tool_key)

    # Fallback: first user-defined callable that isn't a class
    if func is None:
        for name, obj in namespace.items():
            if callable(obj) and not isinstance(obj, type) and not name.startswith("_"):
                func = obj
                break

    if func is None:
        raise RuntimeError(f"No callable found in {file_path}")

    return func(**kwargs)


class OSAgent(BaseAgent):
    """
    Agent responsible for OS-level operations (files, data, system).
    Executes locally via deterministic tools.

    Lookup order:
      1. importlib: tools.builtin.<tool_key>  (prebuilt package)
      2. importlib: projects.<project_id>.tools.<tool_key>  (project module)
      3. exec():    absolute file_path stored in tool_spec  (generated tools)
      4. Simulation fallback (last resort)
    """

    def __init__(self):
        super().__init__("os_agent")

    def execute(self, task: str, **kwargs) -> str:
        tool_key = kwargs.get("tool_key")
        if not tool_key:
            return f"[OSAgent] Executed basic task locally: {task}"

        project_id = kwargs.get("project_id")
        file_path = kwargs.get("file_path")  # from tool_spec
        ask_llm = kwargs.get("ask_llm")       # mid-step LLM callback
        tool_kwargs = kwargs.get("tool_kwargs", {})

        # Inject helpers into tool kwargs
        if ask_llm:
            tool_kwargs["ask_llm"] = ask_llm

        # ------------------------------------------------------------------
        # 1. importlib – builtin tools package
        # ------------------------------------------------------------------
        builtin_paths = [
            f"tools.builtin.{tool_key}",
            "tools.builtin.automl",   # special case
        ]
        if project_id:
            builtin_paths.insert(0, f"projects.{project_id}.tools.{tool_key}")

        for module_path in builtin_paths:
            try:
                if tool_key == "run_flaml_automl":
                    mod = importlib.import_module("tools.builtin.automl")
                    func = getattr(mod, "run_flaml_automl")
                    return str(func(**tool_kwargs))

                mod = importlib.import_module(module_path)
                if hasattr(mod, tool_key):
                    func = getattr(mod, tool_key)
                    return str(func(**tool_kwargs))
            except ImportError:
                continue
            except Exception as e:
                return f"[OSAgent Error] {module_path}.{tool_key}: {e}"

        # ------------------------------------------------------------------
        # 2. exec() from absolute file path (generated tools)
        # ------------------------------------------------------------------
        if file_path:
            try:
                result = _exec_tool_file(file_path, tool_key, **tool_kwargs)
                return str(result)
            except Exception as e:
                # If mid-step LLM available, ask for recovery hint
                if ask_llm:
                    hint = ask_llm(
                        f"Tool '{tool_key}' failed with: {e}. "
                        f"Task was: '{task}'. Provide a short alternative Python snippet or guidance."
                    )
                    return f"[OSAgent] Step failed. LLM guidance: {hint}"
                return f"[OSAgent Error] exec {file_path}: {e}"

        return f"[OSAgent] Successfully simulated local execution of {tool_key} for task: {task}"
