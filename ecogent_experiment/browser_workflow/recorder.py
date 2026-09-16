"""
Browser Recording Agent.

Handles the FIRST RUN of a browser automation task:
  - Communicates with the LLM step-by-step
  - Executes each proposed step via Playwright
  - Records the validated workflow as a BrowserPattern
  - Saves the pattern to Chroma + disk

The recording loop:
  1. Send recording prompt to LLM → LLM returns Step 1 JSON
  2. Execute Step 1 with Playwright
  3. Validate Step 1 deterministically
  4. If fail → ask LLM to correct, retry
  5. Report step result back to LLM → LLM returns Step 2 JSON
  6. Repeat until LLM signals task complete
  7. Save all recorded steps as a BrowserPattern
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from ecogent_experiment.browser_workflow.fingerprint import (
    extract_url_domain,
    fingerprint_to_id,
    task_to_fingerprint,
)
from ecogent_experiment.browser_workflow.pattern_store import BrowserPatternStore
from ecogent_experiment.browser_workflow.playwright_engine import PlaywrightEngine
from ecogent_experiment.browser_workflow.schema import (
    BrowserPattern,
    BrowserReplayResult,
    BrowserStep,
    StepAudit,
)


# ---------------------------------------------------------------------------
# LLM Prompts
# ---------------------------------------------------------------------------

_RECORDING_SYSTEM_PROMPT = """You are a browser automation expert. 
Your job is to guide a browser automation session step by step.

Rules:
- Propose ONE step at a time as a JSON object.
- After each step, you will receive the execution result.
- If a step fails, propose a corrected version.
- When the task is fully complete, respond with:
  {"done": true, "summary": "...description of what was accomplished..."}
- Use specific CSS selectors (prefer #id over .class over tag).
- For dynamic values, use {variable_name} placeholders (e.g. {query}, {category}).
- Keep descriptions concise but clear.

Step JSON format:
{
  "action": {
    "type": "navigate|click|fill|select|extract|wait_for|scroll|key_press",
    ... action-specific fields ...
  },
  "validation": {
    "type": "url_contains|element_exists|element_has_text|element_has_value|extracted_count_gte|page_title_contains|no_error_page|key_press_sent",
    ... validation-specific fields ...
  },
  "description": "What this step does",
  "output_key": null or "key_name_for_extracted_data"
}

Action fields by type:
- navigate:  {"url": "https://..."}
- click:     {"selector": "#css-selector"}
- fill:      {"selector": "#css-selector", "value": "text or {variable}"}
- select:    {"selector": "#css-selector", "option": "value"}
- extract:   {"selector": ".css-selector", "multiple": true/false}
- wait_for:  {"selector": "#css-selector"} OR {"timeout_ms": 2000}
- scroll:    {"direction": "down", "amount": 500}
- key_press: {"key": "Enter"}

Validation fields by type:
- url_contains:        {"value": "substring"}
- element_exists:      {"selector": "#css"}
- element_has_text:    {"selector": "#css", "text": "expected text"}
- element_has_value:   {"selector": "#css", "value": "expected value"}
- extracted_count_gte: {"output_key": "key_name", "count": 1}
- page_title_contains: {"value": "substring"}
- no_error_page:       {}
- key_press_sent:      {}
"""

_RECORDING_START = """Task to automate: "{task}"

No workflow pattern exists yet for this task. You will guide the browser step by step.
The system will execute each step and report back.

Propose Step 1 now."""

_STEP_SUCCESS_FEEDBACK = """Step {step_num} result:
  Status   : SUCCESS ✓
  Validated: {validation_detail}
  Extracted: {extracted}
  URL now  : {url}
  Title    : {title}

Propose Step {next_num}. (Or respond with {{"done": true, "summary": "..."}} if the task is complete.)"""

_STEP_FAILURE_FEEDBACK = """Step {step_num} result:
  Status : FAILED ✗
  Action : {action}
  Error  : {error}
  URL    : {url}
  Title  : {title}
  
Page content (truncated):
{html_snippet}

Please correct Step {step_num} with a different selector or approach."""

_MAX_STEPS = 25        # Safety limit
_MAX_RETRIES_PER_STEP = 3  # Max correction attempts per step


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------

class BrowserRecordingAgent:
    """
    AI-guided browser automation recorder.

    Communicates with the cloud LLM step-by-step, executing each proposed
    action via Playwright and validating the result. On success, saves the
    complete workflow as a reusable BrowserPattern.
    """

    def __init__(
        self,
        pattern_store: BrowserPatternStore,
        cloud_provider,
        headless: bool = True,
        screenshots_dir: Optional[str] = None,
    ):
        self.pattern_store = pattern_store
        self.cloud_provider = cloud_provider
        self.headless = headless
        self.screenshots_dir = screenshots_dir

    def record_and_execute(
        self,
        task: str,
        variables: Optional[Dict[str, str]] = None,
        console=None,
    ) -> BrowserReplayResult:
        """
        Run the recording session: LLM guides → Playwright executes → pattern saved.

        Args:
            task:      The user's browser automation task.
            variables: Variable substitution dict (e.g. {"query": "gaming laptop"}).
            console:   Optional Rich console for output.

        Returns:
            BrowserReplayResult with extracted data, audit log, and cloud_calls count.
        """
        variables = variables or {}
        project_id = self.pattern_store.project_id
        fingerprint = task_to_fingerprint(task)
        pattern_id = fingerprint_to_id(fingerprint)
        domain = extract_url_domain(task)

        def _log(msg: str):
            if console:
                console.print(msg)

        _log(f"\n  [bold cyan][🎬 BROWSER RECORDING][/bold cyan] Starting step-by-step recording...")

        # Build initial conversation
        conversation = (
            f"{_RECORDING_SYSTEM_PROMPT}\n\n"
            f"{_RECORDING_START.format(task=task)}"
        )

        recorded_steps: List[BrowserStep] = []
        step_audit: List[StepAudit] = []
        extracted_data: Dict = {}
        cloud_calls = 0
        ai_recovery_count = 0

        try:
            with PlaywrightEngine(
                headless=self.headless,
                screenshots_dir=self.screenshots_dir,
            ) as engine:
                page = engine.new_page()
                step_num = 1

                for _ in range(_MAX_STEPS):
                    # ── Ask LLM for next step ──────────────────────────
                    raw = self.cloud_provider.generate_plan(conversation)
                    cloud_calls += 1
                    llm_text = raw.get("answer", "")

                    # Check if LLM says done
                    done_data = self._parse_done(llm_text)
                    if done_data:
                        _log(f"  [green]✓[/green] AI: Task complete — {done_data.get('summary', '')}")
                        break

                    # Parse step JSON from LLM response
                    step_json = self._parse_step_json(llm_text)
                    if not step_json:
                        _log(f"  [yellow]⚠[/yellow] LLM response not parseable, asking again...")
                        conversation += f"\n\nSystem: Could not parse your response as JSON. Please respond with a valid step JSON object."
                        continue

                    action = step_json.get("action", {})
                    validation = step_json.get("validation", {})
                    description = step_json.get("description", f"Step {step_num}")
                    output_key = step_json.get("output_key")

                    _log(f"  [dim]Step {step_num}/?: {description}[/dim]")

                    # ── Execute + validate with retry ──────────────────
                    success = False
                    action_result = None
                    validation_result = None
                    this_ai_recovered = False

                    for attempt in range(_MAX_RETRIES_PER_STEP):
                        # Execute
                        action_result = engine.execute_action(page, action, variables)
                        page_ctx = engine.get_page_context(page)

                        if not action_result.success:
                            feedback = _STEP_FAILURE_FEEDBACK.format(
                                step_num=step_num,
                                action=json.dumps(action),
                                error=action_result.error,
                                url=page_ctx.url,
                                title=page_ctx.title,
                                html_snippet=page_ctx.html_snippet[:2000],
                            )
                            conversation += f"\n\nSystem: {feedback}"
                            raw2 = self.cloud_provider.generate_plan(conversation)
                            cloud_calls += 1
                            ai_recovery_count += 1
                            this_ai_recovered = True
                            corrected = self._parse_step_json(raw2.get("answer", ""))
                            if corrected:
                                action = corrected.get("action", action)
                                validation = corrected.get("validation", validation)
                            continue

                        # Collect extracted data
                        if output_key and action_result.extracted_value is not None:
                            extracted_data[output_key] = action_result.extracted_value

                        # Validate
                        validation_result = engine.validate_step(page, validation, extracted_data)
                        page_ctx = engine.get_page_context(page)

                        if validation_result.passed:
                            success = True
                            extracted_str = (
                                f"{len(action_result.extracted_value)} items"
                                if isinstance(action_result.extracted_value, list)
                                else str(action_result.extracted_value or "null")
                            )
                            _log(f"  [green]✓[/green] Step {step_num}: {description}")

                            # Report success back to LLM
                            conversation += "\n\nSystem: " + _STEP_SUCCESS_FEEDBACK.format(
                                step_num=step_num,
                                validation_detail=validation_result.detail,
                                extracted=extracted_str,
                                url=page_ctx.url,
                                title=page_ctx.title,
                                next_num=step_num + 1,
                            )
                            break
                        else:
                            # Validation failed — ask LLM to correct
                            feedback = _STEP_FAILURE_FEEDBACK.format(
                                step_num=step_num,
                                action=json.dumps(action),
                                error=f"Validation failed: {validation_result.detail}",
                                url=page_ctx.url,
                                title=page_ctx.title,
                                html_snippet=page_ctx.html_snippet[:2000],
                            )
                            conversation += f"\n\nSystem: {feedback}"
                            raw3 = self.cloud_provider.generate_plan(conversation)
                            cloud_calls += 1
                            ai_recovery_count += 1
                            this_ai_recovered = True
                            corrected = self._parse_step_json(raw3.get("answer", ""))
                            if corrected:
                                action = corrected.get("action", action)
                                validation = corrected.get("validation", validation)

                    # Record step regardless of final outcome
                    browser_step = BrowserStep(
                        step_id=f"s{step_num}",
                        description=description,
                        action=action,
                        validation=validation,
                        output_key=output_key,
                        fail_count=0 if success else 1,
                        ai_recovered=this_ai_recovered,
                    )
                    recorded_steps.append(browser_step)
                    step_audit.append(StepAudit(
                        step_id=f"s{step_num}",
                        description=description,
                        action_type=action.get("type", "unknown"),
                        validation_passed=success,
                        ai_recovered=this_ai_recovered,
                        extracted=extracted_data.get(output_key) if output_key else None,
                    ))

                    if not success:
                        _log(f"  [red]✗[/red] Step {step_num} failed after {_MAX_RETRIES_PER_STEP} attempts")

                    step_num += 1

        except Exception as e:
            return BrowserReplayResult(
                success=False,
                mode="recording",
                pattern_id=pattern_id,
                cloud_calls=cloud_calls,
                step_audit=step_audit,
                extracted_data=extracted_data,
                error=str(e),
                summary=f"Recording failed: {e}",
            )

        # ── Save the recorded pattern ──────────────────────────────────
        pattern = BrowserPattern(
            pattern_id=pattern_id,
            project_id=project_id,
            task_summary=task[:200],
            fingerprint=fingerprint,
            url_domain=domain,
            run_count=1,
            ai_recovery_count=ai_recovery_count,
            variables=list(variables.keys()),
            steps=recorded_steps,
        )

        self.pattern_store.save_pattern(pattern)
        _log(
            f"\n  [bold green][💾 PATTERN SAVED][/bold green] "
            f"{pattern_id} ({len(recorded_steps)} steps) → Chroma + disk"
        )

        # Build summary
        summary = self._build_summary(task, extracted_data, recorded_steps)

        return BrowserReplayResult(
            success=True,
            mode="recording",
            pattern_id=pattern_id,
            cloud_recovery_count=ai_recovery_count,
            cloud_calls=cloud_calls,
            step_audit=step_audit,
            extracted_data=extracted_data,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_step_json(self, text: str) -> Optional[dict]:
        """Extract and parse the first JSON object from LLM response text."""
        # Try direct JSON parse
        text = text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "action" in data:
                return data
        except Exception:
            pass

        # Find JSON block in markdown code fence
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except Exception:
                pass

        # Find first { ... } block
        brace_match = re.search(r"\{.*\}", text, re.S)
        if brace_match:
            try:
                data = json.loads(brace_match.group(0))
                if isinstance(data, dict) and "action" in data:
                    return data
            except Exception:
                pass

        return None

    def _parse_done(self, text: str) -> Optional[dict]:
        """Check if the LLM response signals task completion."""
        try:
            data = json.loads(text.strip())
            if isinstance(data, dict) and data.get("done"):
                return data
        except Exception:
            pass

        brace_match = re.search(r"\{.*\}", text, re.S)
        if brace_match:
            try:
                data = json.loads(brace_match.group(0))
                if isinstance(data, dict) and data.get("done"):
                    return data
            except Exception:
                pass

        # Natural language completion signals
        done_phrases = [
            "task complete", "task is complete", "task has been completed",
            "all steps done", "workflow complete", "automation complete",
        ]
        if any(p in text.lower() for p in done_phrases):
            summary = re.sub(r"^[^a-zA-Z]*", "", text)[:200]
            return {"done": True, "summary": summary}

        return None

    def _build_summary(
        self,
        task: str,
        extracted_data: dict,
        steps: list,
    ) -> str:
        """Build a human-readable result summary from extracted data."""
        lines = [f"Browser task completed: {task[:100]}"]
        lines.append(f"Steps executed: {len(steps)}")

        for key, value in extracted_data.items():
            if isinstance(value, list):
                lines.append(f"{key}: {len(value)} items extracted")
                # Show first 5 items
                for item in value[:5]:
                    lines.append(f"  - {str(item)[:80]}")
                if len(value) > 5:
                    lines.append(f"  ... and {len(value) - 5} more")
            else:
                lines.append(f"{key}: {str(value)[:200]}")

        return "\n".join(lines)
