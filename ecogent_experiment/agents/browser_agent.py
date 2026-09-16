"""
Browser Agent. Handles web scraping and navigation.
"""

import importlib
import os
from typing import Any

from ecogent_experiment.agents import BaseAgent


def _exec_tool_file(file_path: str, tool_key: str, **kwargs) -> Any:
    """
    Load a tool from an absolute .py file path using exec(),
    find the first callable and call it with kwargs.
    """
    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError(f"Tool file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()

    namespace: dict = {}
    exec(compile(code, file_path, "exec"), namespace)  # noqa: S102

    func = namespace.get(tool_key)
    if func is None:
        for name, obj in namespace.items():
            if callable(obj) and not isinstance(obj, type) and not name.startswith("_"):
                func = obj
                break

    if func is None:
        raise RuntimeError(f"No callable found in {file_path}")

    return func(**kwargs)


class BrowserAgent(BaseAgent):
    """
    Agent responsible for interacting with the web.

    Lookup order:
      1. importlib: tools.builtin.web  (prebuilt web tools: web_search, browse_website)
      2. importlib: projects.<project_id>.tools.<tool_key>  (project module)
      3. exec():    absolute file_path from tool_spec  (generated tools)
      4. Cloud LLM fallback (last resort)
    """

    def __init__(self, cloud_provider=None):
        super().__init__("browser_agent")
        self.cloud_provider = cloud_provider

    def execute(self, task: str, **kwargs) -> str:
        tool_key = kwargs.get("tool_key")
        project_id = kwargs.get("project_id")
        file_path = kwargs.get("file_path")        # from tool_spec
        ask_llm = kwargs.get("ask_llm")             # mid-step LLM callback
        tool_kwargs = kwargs.get("tool_kwargs", {})

        # Always inject task + helpers
        tool_kwargs.setdefault("task", task)
        if ask_llm:
            tool_kwargs["ask_llm"] = ask_llm

        # ------------------------------------------------------------------
        # 0. browser_task — pattern-based Playwright automation (primary path)
        # ------------------------------------------------------------------
        if tool_key == "browser_task":
            try:
                from tools.builtin.browser_automation import browser_task
                result = browser_task(
                    task=task,
                    project_id=project_id or "",
                    cloud_provider=self.cloud_provider,
                    **{k: v for k, v in tool_kwargs.items() if k not in ("task", "ask_llm")},
                )
                if isinstance(result, dict):
                    return result.get("preview", str(result))
                return str(result)
            except Exception as e:
                return f"[BrowserAgent] browser_task failed: {e}"

        if not tool_key:
            return f"[BrowserAgent] Received basic task: {task}"


        # ------------------------------------------------------------------
        # 1. importlib — builtin web module first
        #    web.py exposes: web_search, browse_website, browser_scrape
        # ------------------------------------------------------------------
        web_aliases = {
            "browser_scrape": "browse_website",
            "web_search": "web_search",
            "browse_website": "browse_website",
        }

        # Try the builtin web module for known web tools
        try:
            web_mod = importlib.import_module("tools.builtin.web")
            # Check exact match or alias
            func_name = web_aliases.get(tool_key, tool_key)
            if hasattr(web_mod, func_name):
                func = getattr(web_mod, func_name)
                result = func(**tool_kwargs)
                if isinstance(result, dict):
                    return result.get("preview", str(result))
                return str(result)
        except ImportError:
            pass
        except Exception as e:
            return f"[BrowserAgent Error] tools.builtin.web.{tool_key}: {e}"

        # ------------------------------------------------------------------
        # 2. importlib — project-specific or generated module paths
        # ------------------------------------------------------------------
        search_paths = [f"tools.builtin.web", f"tools.generated.{tool_key}"]
        if project_id:
            search_paths.insert(0, f"projects.{project_id}.tools.{tool_key}")

        for module_path in search_paths:
            try:
                mod = importlib.import_module(module_path)
                if hasattr(mod, tool_key):
                    func = getattr(mod, tool_key)
                    result = func(**tool_kwargs)
                    if isinstance(result, dict):
                        return result.get("preview", str(result))
                    return str(result)
            except ImportError:
                continue
            except Exception as e:
                return f"[BrowserAgent Error] {module_path}.{tool_key}: {e}"

        # ------------------------------------------------------------------
        # 3. exec() from absolute file path (generated tools)
        # ------------------------------------------------------------------
        if file_path:
            try:
                result = _exec_tool_file(file_path, tool_key, **tool_kwargs)
                if isinstance(result, dict):
                    return result.get("preview", str(result))
                return str(result)
            except Exception as e:
                if ask_llm:
                    hint = ask_llm(
                        f"Browser tool '{tool_key}' failed with: {e}. "
                        f"Task was: '{task}'. Provide a short alternative or guidance."
                    )
                    return f"[BrowserAgent] Step failed. LLM guidance: {hint}"
                return f"[BrowserAgent Error] exec {file_path}: {e}"

        # ------------------------------------------------------------------
        # 4. Cloud LLM fallback
        # ------------------------------------------------------------------
        if self.cloud_provider:
            result = self.cloud_provider.generate_plan(task)
            return result.get("answer", "")

        return f"[BrowserAgent Error] Could not find or execute tool '{tool_key}' for: {task}"
