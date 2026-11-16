"""
Model routing check: which model answers which LLM job (purpose).

    python bench/routing_check.py            free: mock clients, no API call
    python bench/routing_check.py --real     + one tiny real call per configured model (a fraction of a cent)

Checks, with the saved Settings (main model, cheap model, cheap_purposes):
  1. every purpose in cheap_purposes goes to the cheap model, every other purpose to the main model
  2. a failing cheap model falls back to the main model, recorded as "<purpose>:fallback"
  3. with the cheap model off (the benchmark's no_cheap variant) everything goes to the main model
  4. (--real) both models answer, and the model name the provider reports matches the setting
Prints the routing table and "ROUTING OK". Never prints API keys.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecogent import llm as L                                  # noqa: E402
from ecogent.config import LLM_PURPOSES, Settings             # noqa: E402


def _mock_router(s: Settings, fail_cheap: bool = False):
    """A router whose clients answer locally and report which config served the call."""
    calls: list[tuple[str, str]] = []

    def fake_complete(self, system, messages, max_tokens=None, json_mode=False):
        if fail_cheap and self.cfg is s.cheap_llm:
            raise L.LLMError("simulated cheap-model failure")
        return L.LLMResponse("{}", 10, 2, self.cfg.model, self.cfg.provider)
    orig = L.LLMClient.complete
    L.LLMClient.complete = fake_complete
    r = L.LLMRouter(s, on_usage=lambda purpose, resp: calls.append((purpose, resp.model)))
    return r, calls, orig


def mock_checks(s: Settings) -> list[str]:
    problems = []
    cheap_on = s.cheap_llm.enabled
    # 1. routing per purpose
    r, calls, orig = _mock_router(s)
    try:
        for p in LLM_PURPOSES:
            r.ask(p, "system", "user")
    finally:
        L.LLMClient.complete = orig
    print(f"\nMain model:  {s.main_llm.provider}:{s.main_llm.model}")
    print(f"Cheap model: {s.cheap_llm.provider + ':' + s.cheap_llm.model if cheap_on else 'off'}")
    print(f"cheap_purposes: {', '.join(s.cheap_purposes) or '(none)'}\n")
    print(f"  {'purpose':12} {'model used':32} expected")
    for (purpose, model) in calls:
        want = s.cheap_llm.model if cheap_on and purpose in s.cheap_purposes else s.main_llm.model
        ok = model == want
        print(f"  {purpose:12} {model:32} {'cheap' if want == s.cheap_llm.model and cheap_on and purpose in s.cheap_purposes else 'main'}"
              f"{'' if ok else '   <-- WRONG'}")
        if not ok:
            problems.append(f"{purpose} went to {model}, expected {want}")
    unknown = [p for p in s.cheap_purposes if p not in LLM_PURPOSES]
    if unknown:
        problems.append(f"cheap_purposes has unknown names: {unknown}")
    # 2. fallback
    if cheap_on and s.cheap_purposes:
        r, calls, orig = _mock_router(s, fail_cheap=True)
        try:
            r.ask(s.cheap_purposes[0], "system", "user")
        finally:
            L.LLMClient.complete = orig
        fb = calls[-1] if calls else ("", "")
        print(f"\nCheap model failing on '{s.cheap_purposes[0]}': recorded as '{fb[0]}' on {fb[1]}")
        if fb != (f"{s.cheap_purposes[0]}:fallback", s.main_llm.model):
            problems.append(f"fallback recorded as {fb}")
    # 3. no_cheap variant
    nc = Settings._from_dict(json.loads(json.dumps(s.__dict__, default=lambda o: o.__dict__)))
    nc.cheap_llm.provider = "none"
    r, calls, orig = _mock_router(nc)
    try:
        for p in LLM_PURPOSES:
            r.ask(p, "system", "user")
    finally:
        L.LLMClient.complete = orig
    wrong = [p for p, m in calls if m != nc.main_llm.model]
    print(f"no_cheap variant: {len(calls) - len(wrong)}/{len(calls)} purposes on the main model")
    if wrong:
        problems.append(f"no_cheap still routes {wrong} to another model")
    if cheap_on and s.cheap_llm.model == s.main_llm.model:
        print("\nWARNING: main and cheap are the same model, so routing saves nothing.")
    return problems


def real_checks(s: Settings) -> list[str]:
    problems = []
    print("\nReal calls (one tiny request per model; 'served by' is the model name in the provider's reply):")
    raw: dict = {}
    orig_post = L._post

    def spy_post(url, body, headers, timeout):
        raw["data"] = orig_post(url, body, headers, timeout)
        return raw["data"]
    L._post = spy_post
    try:
        for name, cfg in (("main", s.main_llm), ("cheap", s.cheap_llm)):
            if not cfg.enabled:
                continue
            raw.clear()
            try:
                resp = L.LLMClient(cfg).complete("Reply with the single word OK.", [{"role": "user", "content": "Ping"}], 5)
            except L.LLMError as e:
                problems.append(f"{name} model call failed: {str(e)[:160]}")
                print(f"  {name:5} {cfg.model:24} FAILED: {str(e)[:120]}")
                continue
            served = str((raw.get("data") or {}).get("model") or "(not reported)")
            same = served == "(not reported)" or served.split("/")[-1].startswith(cfg.model.split("/")[-1])
            print(f"  {name:5} asked {cfg.model:24} served by {served:34} '{resp.text.strip()[:12]}'  "
                  f"tokens {resp.input_tokens}/{resp.output_tokens}")
            if not same:
                problems.append(f"{name}: asked for {cfg.model}, provider served {served}")
    finally:
        L._post = orig_post
    return problems


def main() -> None:
    s = Settings.load()
    problems = mock_checks(s)
    if "--real" in sys.argv:
        problems += real_checks(s)
    if problems:
        print("\nROUTING PROBLEMS:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("\nROUTING OK")


if __name__ == "__main__":
    main()
