"""
Tool registry: every step action the LLM may use, defined once.

The planner prompt lists only the tools of the chat's task type, and the executor runs
Executor.act_<name> for each step. To add a tool: add a Tool here and an act_<name> method.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ALL = ()  # empty = available for every task type


@dataclass(frozen=True)
class Tool:
    name: str
    params: str
    desc: str
    group: str                   # browser | page | flow | file | output
    types: tuple = ALL
    browser: bool = False


TOOLS: tuple[Tool, ...] = (
    # ---- browser control (Playwright)
    Tool("open_url", "url, fallback_url?", "open a page", "browser", browser=True),
    Tool("fill", "target, value", "type into a field (target = plain-language description)", "browser", browser=True),
    Tool("click", "target", "click an element", "browser", browser=True),
    Tool("press", "key, target?", "press a key, e.g. Enter", "browser", browser=True),
    Tool("select_option", "target, value", "choose a dropdown option", "browser", browser=True),
    Tool("scroll", "times", "scroll down", "browser", browser=True),
    Tool("wait", "seconds | target", "wait for time or until an element is visible", "browser", browser=True),
    Tool("screenshot", "label", "save a screenshot to the temp folder", "browser", browser=True),
    Tool("download", "target, save_as?", "click a download link/button and save the file into the output folder", "browser", browser=True),
    Tool("upload", "target, value (file path)", "attach a local file to a file input", "browser", ("automation", "others"), browser=True),
    Tool("save_session", "", "store cookies/storage so the login can be reused", "browser", ("automation", "others"), browser=True),
    # ---- page data (BeautifulSoup)
    Tool("get_page_data", "label", "save the main text of the current page as a data file", "page", browser=True),
    Tool("collect_links", "target, limit, save_as", "collect matching links into a variable", "page", browser=True),
    Tool("extract_records", "", "build/reuse a CSS pattern, sample, validate, scrape all pages", "page", ("scraping", "others"), browser=True),
    # ---- flow
    Tool("for_each", "source, limit, dedupe, steps", "run nested steps for each item of a list variable; "
         "{{item}} is the current item; dedupe=true skips items handled in earlier runs", "flow"),
    Tool("ask_user", "message", "pause for the human (login, captcha, credentials, confirmation)", "flow"),
    # ---- built-in local file operations
    Tool("list_files", "path?, pattern?, recursive?, save_as", "list files (e.g. pattern '*.pdf') into a list variable", "file"),
    Tool("read_file", "path, save_as?, as_data?", "read txt/md/json/csv/xlsx/docx; as_data=true adds it to the "
         "collected data for analyze", "file"),
    Tool("write_file", "path, value", "write text to a file", "file"),
    Tool("append_file", "path, value", "append text to a file", "file"),
    Tool("copy_file", "path, dest", "copy a file or folder", "file"),
    Tool("move_file", "path, dest", "move/rename a file or folder", "file"),
    Tool("delete_file", "path", "delete a file or folder (only inside Ecogent / selected folders)", "file"),
    Tool("make_dir", "path", "create a folder", "file"),
    Tool("file_exists", "path, save_as", "store 'true'/'false' in a variable", "file"),
    # ---- results
    Tool("analyze", "instructions", "LLM analyzes all collected data and writes the final output file", "output", ("analysis", "others")),
    Tool("write_output", "", "write scraped records (or the automation's handled items) to the output file", "output",
         ("scraping", "automation", "others")),
)

REGISTRY: dict[str, Tool] = {t.name: t for t in TOOLS}

GROUP_TITLES = {
    "browser": "Browser (Playwright)",
    "page": "Page data (BeautifulSoup)",
    "flow": "Flow",
    "file": "Local files (paths relative to the selected folder, else the output folder)",
    "output": "Results",
}


def tools_for(task_type: str) -> list[Tool]:
    return [t for t in TOOLS if not t.types or task_type in t.types]


def allowed(name: str, task_type: str) -> bool:
    t = REGISTRY.get(name)
    return bool(t) and (not t.types or task_type in t.types)


def catalog(task_type: str) -> str:
    """Tool list for the system prompt, only the tools of this task type, one compact line each
    (no column padding: whitespace is billed too). A flat list on purpose: with group headings
    ("[Browser]", "[Results]") small models used the heading as the action."""
    tools = tools_for(task_type)
    lines = ['TOOLS - "action" must be one of these names exactly:']
    for group in GROUP_TITLES:
        lines += [f"- {t.name}({t.params}): {t.desc}" for t in tools if t.group == group]
    if any(t.group == "file" for t in tools):
        lines.append("File paths are relative to the selected folder, else the output folder.")
    return "\n".join(lines)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2}


def guess(step: dict, task_type: str) -> str:
    """The real tool for a step whose "action" is not a tool name ("Browser", "Page data",
    "open url", "Results"): exact after normalizing, else the clear best match by the step's
    fields and name, restricted to the group the wrong name points at. '' when unsure."""
    raw = str(step.get("action") or "")
    norm = re.sub(r"[\s\-]+", "_", raw.strip().lower())
    if allowed(norm, task_type):
        return norm
    tools = tools_for(task_type)
    aw = _words(raw)
    groups = {g for g, title in GROUP_TITLES.items() if aw & (_words(title) | {g})}
    pool = [t for t in tools if t.group in groups] or tools
    if len(pool) == 1:
        return pool[0].name
    # A group name only chooses the group; inside it the step's own name decides.
    hint = _words(step.get("step_name", "")) | (set() if groups else aw)
    keys = {k for k in step if k not in ("id", "step_name", "action", "on_fail", "validation")}

    def score(t: Tool) -> float:
        params = {p.strip(" ?").split(" ")[0] for p in re.split(r"[,|]", t.params) if p.strip()}
        return 2 * len(hint & _words(t.name.replace("_", " "))) + len(keys & params) + 0.5 * len(hint & _words(t.desc))
    ranked = sorted(((score(t), t.name) for t in pool), reverse=True)
    if ranked[0][0] > 0 and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
        return ranked[0][1]
    return ""


def repair_steps(steps: list, task_type: str, log=None) -> int:
    """Fix wrong action names in place (nested steps too), with no LLM call. Returns the count."""
    fixed = 0
    for st in steps or []:
        if not isinstance(st, dict):
            continue
        if not allowed(str(st.get("action")), task_type):
            new = guess(st, task_type)
            if new:
                if log:
                    log(f"Step {st.get('id')}: action '{st.get('action')}' is not a tool; using '{new}' (no LLM)")
                st["action"] = new
                fixed += 1
        fixed += repair_steps(st.get("steps") or [], task_type, log)
    return fixed
