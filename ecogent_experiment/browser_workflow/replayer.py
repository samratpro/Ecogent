"""
Browser Replay Engine.

Handles SUBSEQUENT RUNS of a recorded browser automation pattern:
  - Loads saved BrowserPattern (steps + actions + validations)
  - Executes all steps via Playwright (zero AI calls on clean run)
  - Validates each step deterministically
  - On validation failure: calls AI for that step ONLY, updates the selector in the pattern
  - Saves updated pattern to disk (healed selectors persist for next run)

This is the cost-saving core: cloud_calls=0 on a clean replay.
"""

import json
from typing import Callable, Dict, Optional

from ecogent_experiment.browser_workflow.pattern_store import BrowserPatternStore
from ecogent_experiment.browser_workflow.playwright_engine import PlaywrightEngine
from ecogent_experiment.browser_workflow.schema import (
    BrowserPattern,
    BrowserReplayResult,
    StepAudit,
)


# ---------------------------------------------------------------------------
# AI Recovery Prompt
# ---------------------------------------------------------------------------

_AI_RECOVERY_PROMPT = """A browser automation step failed during replay.

Step description : {description}
Action attempted : {action_json}
Validation rule  : {validation_json}
Validation error : {error}

Current page state:
  URL  : {url}
  Title: {title}

Page content (truncated):
{html_snippet}

Provide a corrected action JSON for this step ONLY.
Output ONLY the corrected action JSON object (no explanation, no markdown).
Example: {{"type": "click", "selector": "#new-selector"}}"""

_MAX_RETRIES_PER_STEP = 3


class BrowserReplayEngine:
    """
    Zero-AI browser replay engine.

    Replays a saved BrowserPattern without any cloud LLM calls unless
    a validation step fails, in which case the AI is called for that
    step only to provide a corrected selector/action.

    Self-healing: recovered selectors are written back to the pattern
    JSON on disk, so future replays won't need recovery.
    """

    def __init__(self, cloud_provider=None, headless: bool = True):
        self.cloud_provider = cloud_provider
        self.headless = headless

    def replay(
        self,
        pattern: BrowserPattern,
        pattern_store: BrowserPatternStore,
        variables: Optional[Dict[str, str]] = None,
        console=None,
    ) -> BrowserReplayResult:
        """
        Replay a saved browser pattern.

        Args:
            pattern:       The BrowserPattern to replay.
            pattern_store: Used to persist healed patterns after replay.
            variables:     Variable substitution dict (e.g. {"query": "phones"}).
            console:       Optional Rich console for progress output.

        Returns:
            BrowserReplayResult with extracted data, audit, and cloud_calls count.
        """
        variables = variables or {}

        def _log(msg: str):
            if console:
                console.print(msg)

        _log(
            f"\n  [bold cyan][▶ BROWSER REPLAY][/bold cyan] "
            f"Executing {len(pattern.steps)} steps without AI..."
        )

        step_audit = []
        extracted_data = {}
        cloud_calls = 0
        ai_recovery_count = 0
        pattern_modified = False

        try:
            with PlaywrightEngine(headless=self.headless) as engine:
                page = engine.new_page()

                for i, step in enumerate(pattern.steps, 1):
                    _log(f"  [dim]Step {i}/{len(pattern.steps)}: {step.description}[/dim]")

                    action = step.action
                    validation = step.validation
                    output_key = step.output_key
                    step_success = False
                    this_ai_recovered = False
                    step_error = None

                    for attempt in range(_MAX_RETRIES_PER_STEP):
                        # ── Execute ────────────────────────────────────
                        action_result = engine.execute_action(page, action, variables)
                        page_ctx = engine.get_page_context(page)

                        if not action_result.success:
                            if attempt < _MAX_RETRIES_PER_STEP - 1 and self.cloud_provider:
                                corrected = self._ai_recover_action(
                                    step=step,
                                    action=action,
                                    validation=validation,
                                    error=action_result.error or "Action failed",
                                    page_ctx=page_ctx,
                                )
                                cloud_calls += 1
                                ai_recovery_count += 1
                                this_ai_recovered = True
                                if corrected:
                                    action = corrected
                                    step_error = None
                                    continue
                            step_error = action_result.error
                            break

                        # Collect extracted data
                        if output_key and action_result.extracted_value is not None:
                            extracted_data[output_key] = action_result.extracted_value

                        # ── Validate ───────────────────────────────────
                        validation_result = engine.validate_step(page, validation, extracted_data)
                        page_ctx = engine.get_page_context(page)

                        if validation_result.passed:
                            step_success = True
                            extracted_str = (
                                f"{len(action_result.extracted_value)} items"
                                if isinstance(action_result.extracted_value, list)
                                else str(action_result.extracted_value or "—")
                            )
                            _log(
                                f"  [green]✓[/green] Step {i}/{len(pattern.steps)}: "
                                f"{step.description}"
                                + (f" ({extracted_str})" if output_key else "")
                            )
                            break

                        else:
                            # Validation failed — try AI recovery
                            if attempt < _MAX_RETRIES_PER_STEP - 1 and self.cloud_provider:
                                corrected = self._ai_recover_action(
                                    step=step,
                                    action=action,
                                    validation=validation,
                                    error=f"Validation failed: {validation_result.detail}",
                                    page_ctx=page_ctx,
                                )
                                cloud_calls += 1
                                ai_recovery_count += 1
                                this_ai_recovered = True
                                if corrected:
                                    action = corrected
                                    # Update the pattern step with healed action
                                    step.action = action
                                    step.ai_recovered = True
                                    step.fail_count += 1
                                    pattern_modified = True
                                    continue

                            step_error = f"Validation failed: {validation_result.detail}"
                            break

                    # Update step audit
                    if this_ai_recovered:
                        icon = "[yellow]~[/yellow]" if step_success else "[red]✗[/red]"
                        _log(f"  {icon} Step {i}: AI recovered {'✓' if step_success else '✗'}")

                    step_audit.append(StepAudit(
                        step_id=step.step_id,
                        description=step.description,
                        action_type=action.get("type", "unknown"),
                        validation_passed=step_success,
                        ai_recovered=this_ai_recovered,
                        error=step_error,
                        extracted=extracted_data.get(output_key) if output_key else None,
                    ))

                    if not step_success:
                        _log(f"  [red]✗[/red] Step {i} failed: {step_error}")

        except Exception as e:
            return BrowserReplayResult(
                success=False,
                mode="replay",
                pattern_id=pattern.pattern_id,
                cloud_calls=cloud_calls,
                step_audit=step_audit,
                extracted_data=extracted_data,
                error=str(e),
                summary=f"Replay failed at step: {e}",
            )

        # ── Persist healed pattern ──────────────────────────────────────
        pattern.touch()
        pattern.ai_recovery_count += ai_recovery_count
        if pattern_modified or ai_recovery_count > 0:
            pattern_store.update_after_replay(pattern)

        all_passed = all(a.validation_passed for a in step_audit)

        summary = self._build_summary(pattern, extracted_data, step_audit, cloud_calls)

        return BrowserReplayResult(
            success=all_passed,
            mode="replay",
            pattern_id=pattern.pattern_id,
            cloud_recovery_count=ai_recovery_count,
            cloud_calls=cloud_calls,
            step_audit=step_audit,
            extracted_data=extracted_data,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # AI Recovery
    # ------------------------------------------------------------------

    def _ai_recover_action(
        self,
        step,
        action: dict,
        validation: dict,
        error: str,
        page_ctx,
    ) -> Optional[dict]:
        """
        Ask the cloud AI for a corrected action when validation fails.

        Returns the corrected action dict, or None if recovery failed.
        """
        if not self.cloud_provider:
            return None

        prompt = _AI_RECOVERY_PROMPT.format(
            description=step.description,
            action_json=json.dumps(action),
            validation_json=json.dumps(validation),
            error=error,
            url=page_ctx.url,
            title=page_ctx.title,
            html_snippet=page_ctx.html_snippet[:2500],
        )

        try:
            result = self.cloud_provider.generate_plan(prompt)
            answer = result.get("answer", "").strip()

            # Parse corrected action JSON
            import re
            try:
                corrected = json.loads(answer)
                if isinstance(corrected, dict) and "type" in corrected:
                    return corrected
            except Exception:
                pass

            # Try extracting JSON from the response
            match = re.search(r"\{.*\}", answer, re.S)
            if match:
                corrected = json.loads(match.group(0))
                if isinstance(corrected, dict) and "type" in corrected:
                    return corrected

        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        pattern: BrowserPattern,
        extracted_data: dict,
        step_audit: list,
        cloud_calls: int,
    ) -> str:
        """Build human-readable summary of the replay result."""
        passed = sum(1 for a in step_audit if a.validation_passed)
        total = len(step_audit)

        lines = [
            f"**Browser replay complete** — {passed}/{total} steps succeeded",
            f"Pattern: {pattern.task_summary[:80]}",
            f"Cloud AI calls: {cloud_calls} (0 = full replay, >0 = self-healing applied)",
        ]

        if extracted_data:
            lines.append("\n**Extracted Data:**")
            for key, value in extracted_data.items():
                if isinstance(value, list):
                    lines.append(f"\n**{key}** ({len(value)} items):")
                    for item in value[:10]:
                        lines.append(f"  - {str(item)[:100]}")
                    if len(value) > 10:
                        lines.append(f"  ... and {len(value) - 10} more")
                else:
                    lines.append(f"\n**{key}**: {str(value)[:200]}")

        return "\n".join(lines)
