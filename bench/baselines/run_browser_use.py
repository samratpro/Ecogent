"""
Baseline runner: browser-use (runs in .venv-baselines, called by bench/drift_bench.py).

    .venv-baselines/Scripts/python bench/baselines/run_browser_use.py <config.json>

config.json: {"prompt", "out_dir", "llm": {"provider", "model", "base_url"}, "browser": {"executable",
"headless"}, "max_steps", "timeout_s"}. The API key comes from the BENCH_LLM_KEY environment
variable (never written to disk). Writes <out_dir>/result.json:
{"status", "claimed_success", "final_text", "files", "calls", "input_tokens", "output_tokens",
 "cached_input_tokens", "model", "steps", "error"}

browser-use runs with its default agent settings (vision on, as shipped). Changed only: no captcha
solver (the study never bypasses captchas), no default browser extensions (they alter pages), no
telemetry, its own temporary browser profile per run. browser-use keeps no memory between runs
(it is the "LLM decides every step, every run" baseline).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")
os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "warning")


def make_llm(cfg: dict, key: str):
    provider, model, base = cfg["provider"], cfg["model"], cfg.get("base_url") or None
    if provider == "anthropic":
        from browser_use.llm.anthropic.chat import ChatAnthropic
        return ChatAnthropic(model=model, api_key=key, temperature=0)
    if provider == "openrouter":
        from browser_use.llm.openrouter.chat import ChatOpenRouter
        return ChatOpenRouter(model=model, api_key=key, temperature=0)
    from browser_use.llm.openai.chat import ChatOpenAI
    return ChatOpenAI(model=model, api_key=key, base_url=base, temperature=0)


async def run(cfg: dict) -> dict:
    from browser_use import Agent, BrowserProfile, BrowserSession
    out = Path(cfg["out_dir"])
    llm = make_llm(cfg["llm"], os.environ.get("BENCH_LLM_KEY", ""))
    profile = BrowserProfile(executable_path=cfg["browser"].get("executable") or None,
                             headless=bool(cfg["browser"].get("headless")), enable_default_extensions=False,
                             captcha_solver=False, user_data_dir=str(out / "profile"), keep_alive=False)
    session = BrowserSession(browser_profile=profile)
    agent = Agent(task=cfg["prompt"], llm=llm, browser_session=session, file_system_path=str(out / "fs"),
                  calculate_cost=True)
    history = await agent.run(max_steps=int(cfg.get("max_steps", 60)))
    u = history.usage
    data_dir = out / "fs" / "browseruse_agent_data"
    files = sorted(str(p) for p in data_dir.glob("*") if p.is_file() and p.name != "todo.md") if data_dir.exists() else []
    return {"status": "done" if history.is_done() else "failed", "claimed_success": history.is_successful(),
            "final_text": history.final_result() or "", "files": files,
            "calls": getattr(u, "entry_count", 0) if u else 0,
            "input_tokens": getattr(u, "total_prompt_tokens", 0) if u else 0,
            "output_tokens": getattr(u, "total_completion_tokens", 0) if u else 0,
            "cached_input_tokens": getattr(u, "total_prompt_cached_tokens", 0) if u else 0,
            "model": f"{cfg['llm']['provider']}:{cfg['llm']['model']}", "steps": len(history.history), "error": ""}


def main() -> None:
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(cfg["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        res = asyncio.run(asyncio.wait_for(run(cfg), timeout=float(cfg.get("timeout_s", 900))))
    except asyncio.TimeoutError:
        res = {"status": "timeout", "error": f"no result after {cfg.get('timeout_s')} s"}
    except Exception as e:                      # noqa: BLE001 - report, the benchmark continues
        res = {"status": "failed", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
    res["seconds"] = round(time.time() - t0, 1)
    (out / "result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
