"""
Settings: folders, browser options and LLM providers.

Stored in ecogent_data/settings.json (git-ignored, it may contain API keys).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOME = ROOT / "ecogent_data"
SETTINGS_FILE = DEFAULT_HOME / "settings.json"

TASK_TYPES = ["analysis", "scraping", "automation", "software_test", "others"]
NOT_IMPLEMENTED_TYPES = {"software_test"}   # placeholder: listed in the GUI, not implemented yet
TASK_LABELS = {
    "analysis": "Analysis",
    "scraping": "Data Scrap",
    "automation": "Automation",
    "software_test": "Software Test",
    "others": "Others",
}

# Two models: the main (strong) model and an optional cheap model for low-level jobs. These are
# the jobs that may be routed to the cheap model; planning, healing and the final analysis stay
# on the main model by default. (Ecogent has no local / tiny model: both are API models.)
LLM_PURPOSES = ["plan", "followup", "pick", "locate", "heal", "rescue", "pattern", "validate", "analyze_map",
                "analyze", "classify", "repair"]
CHEAP_PURPOSES_DEFAULT = ["pick", "validate", "analyze_map", "classify", "repair"]


# Provider presets. All except "anthropic" speak the OpenAI-compatible /chat/completions API.
PROVIDERS = {
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "needs_key": True},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "needs_key": True},
    "compatible": {"label": "Custom OpenAI-compatible", "base_url": "", "needs_key": False},
    "anthropic": {"label": "Anthropic", "base_url": "https://api.anthropic.com", "needs_key": True},
}
OPENAI_STYLE = {"openai", "openrouter", "compatible"}


@dataclass
class LLMConfig:
    provider: str = "openai"          # openai | openrouter | compatible | anthropic | none
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    max_tokens: int = 4096
    temperature: float = 0.1
    timeout: int = 120

    @property
    def enabled(self) -> bool:
        return self.provider != "none" and bool(self.model)


def _cheap_llm_default() -> LLMConfig:
    # The cheap model for low-level jobs (e.g. gpt-4o-mini, a flash / haiku model).
    # Off until a provider is chosen in Settings.
    return LLMConfig(provider="none", base_url=PROVIDERS["openai"]["base_url"], model="gpt-4o-mini", max_tokens=1024)


def _api_only(cfg: LLMConfig, key: str) -> LLMConfig:
    """Local model servers (Ollama) are no longer supported: an old local config is replaced by
    the API default (the cheap slot stays off until a provider is chosen)."""
    if cfg.provider == "ollama" or "localhost:11434" in (cfg.base_url or ""):
        return _cheap_llm_default() if key == "cheap_llm" else LLMConfig()
    return cfg


@dataclass
class Settings:
    home: str = str(DEFAULT_HOME)
    temp_dir: str = ""                # default: <home>/temp
    output_dir: str = ""              # default: <home>/output
    profile_dir: str = ""             # default: <home>/profiles
    headless: bool = False
    browser_path: str = ""            # empty = auto-detect (Brave, Comet, Edge, Chrome, Chromium)
    browser_language: str = "en-US"   # --lang / --accept-lang for the browser; empty = system / IP default
    # Profile new tasks use. A persistent profile keeps cookies (logins, Google's captcha
    # exemption) between runs; a fresh temporary profile looks like a new device every run and
    # gets captchas. Created automatically on first use. "" = temporary profile.
    default_profile: str = "default"
    debug_port: int = 9231
    page_timeout_ms: int = 45000
    # Defaults for new tasks (each task can override them in the New task dialog):
    page_wait_s: int = 0              # extra pause after every page load (slow / JS-heavy sites)
    bot_check_wait_s: int = 15        # a verification screen ("Just a moment...") is re-checked this
                                      # long for it to pass by itself before the user is asked
    main_llm: LLMConfig = field(default_factory=LLMConfig)
    cheap_llm: LLMConfig = field(default_factory=_cheap_llm_default)
    cheap_purposes: list = field(default_factory=lambda: list(CHEAP_PURPOSES_DEFAULT))
    max_heal_attempts: int = 2        # per step
    max_heals_per_run: int = 6        # across all steps / for_each items of one run
    max_rescue_turns: int = 3         # ReAct fallback: moves per step when heal could not fix it (0 = off)
    max_rescues_per_run: int = 2      # steps per run that may use the ReAct fallback
    max_run_tokens: int = 150000      # per-run token budget; asks before going over (0 = unlimited)
    scrape_sample_size: int = 15
    max_page_chars: int = 12000
    analysis_direct_chars: int = 30000
    analysis_budget_chars: int = 24000   # relevance filter: max chars of page text sent to analysis (0 = off)
    use_vector_memory: bool = True

    # ------------------------------------------------------------------ paths
    @property
    def home_path(self) -> Path:
        return Path(self.home)

    @property
    def chats_path(self) -> Path:
        return self.home_path / "chats"

    @property
    def temp_path(self) -> Path:
        return Path(self.temp_dir) if self.temp_dir else self.home_path / "temp"

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir) if self.output_dir else self.home_path / "output"

    @property
    def profile_path(self) -> Path:
        return Path(self.profile_dir) if self.profile_dir else self.home_path / "profiles"

    @property
    def schedules_file(self) -> Path:
        return self.home_path / "schedules.json"

    def ensure_dirs(self) -> None:
        for p in (self.home_path, self.chats_path, self.temp_path, self.output_path, self.profile_path):
            p.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        if SETTINGS_FILE.exists():
            try:
                raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                s = cls._from_dict(raw)
            except Exception:
                pass
        if not s.main_llm.api_key:
            s.main_llm.api_key = os.environ.get("ECOGENT_API_KEY", "")
        s.ensure_dirs()
        return s

    @classmethod
    def _from_dict(cls, raw: dict) -> "Settings":
        raw = dict(raw)
        # Older settings files: the cheap model was the "local_llm" (a tiny local model).
        if "local_llm" in raw and "cheap_llm" not in raw:
            raw["cheap_llm"] = raw["local_llm"]
        if "local_purposes" in raw and "cheap_purposes" not in raw:
            raw["cheap_purposes"] = raw["local_purposes"]
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known}
        llm_known = {f.name for f in fields(LLMConfig)}
        for key in ("main_llm", "cheap_llm"):
            if isinstance(data.get(key), dict):
                data[key] = _api_only(LLMConfig(**{k: v for k, v in data[key].items() if k in llm_known}), key)
        return cls(**data)

    def save(self) -> None:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        self.ensure_dirs()
