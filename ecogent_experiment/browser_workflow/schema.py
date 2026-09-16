"""
Browser Workflow Schema.

Pydantic models for the browser automation pattern system.
All data structures used by the recorder, replayer, and pattern store.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Action Types
# ---------------------------------------------------------------------------

class NavigateAction(BaseModel):
    type: Literal["navigate"] = "navigate"
    url: str


class ClickAction(BaseModel):
    type: Literal["click"] = "click"
    selector: str


class FillAction(BaseModel):
    type: Literal["fill"] = "fill"
    selector: str
    value: str  # Supports {variable} placeholders


class SelectAction(BaseModel):
    type: Literal["select"] = "select"
    selector: str
    option: str  # Option value or visible text


class ExtractAction(BaseModel):
    type: Literal["extract"] = "extract"
    selector: str
    multiple: bool = False  # True = all_inner_texts(), False = inner_text()


class WaitForAction(BaseModel):
    type: Literal["wait_for"] = "wait_for"
    selector: Optional[str] = None   # Wait for element
    timeout_ms: Optional[int] = None  # Or wait N milliseconds


class ScrollAction(BaseModel):
    type: Literal["scroll"] = "scroll"
    direction: Literal["down", "up", "left", "right"] = "down"
    amount: int = 500  # pixels


class ScreenshotAction(BaseModel):
    type: Literal["screenshot"] = "screenshot"
    output_key: str = "screenshot"


class KeyPressAction(BaseModel):
    type: Literal["key_press"] = "key_press"
    key: str  # e.g. "Enter", "Tab", "Escape"


# Discriminated union of all action types
BrowserAction = Union[
    NavigateAction,
    ClickAction,
    FillAction,
    SelectAction,
    ExtractAction,
    WaitForAction,
    ScrollAction,
    ScreenshotAction,
    KeyPressAction,
]


# ---------------------------------------------------------------------------
# Validation Types
# ---------------------------------------------------------------------------

class UrlContainsValidation(BaseModel):
    type: Literal["url_contains"] = "url_contains"
    value: str


class ElementExistsValidation(BaseModel):
    type: Literal["element_exists"] = "element_exists"
    selector: str


class ElementHasTextValidation(BaseModel):
    type: Literal["element_has_text"] = "element_has_text"
    selector: str
    text: str


class ElementHasValueValidation(BaseModel):
    type: Literal["element_has_value"] = "element_has_value"
    selector: str
    value: str


class ExtractedCountGteValidation(BaseModel):
    type: Literal["extracted_count_gte"] = "extracted_count_gte"
    output_key: str
    count: int = 1


class PageTitleContainsValidation(BaseModel):
    type: Literal["page_title_contains"] = "page_title_contains"
    value: str


class NoErrorPageValidation(BaseModel):
    type: Literal["no_error_page"] = "no_error_page"


class KeyPressSentValidation(BaseModel):
    type: Literal["key_press_sent"] = "key_press_sent"


# Discriminated union of all validation types
StepValidation = Union[
    UrlContainsValidation,
    ElementExistsValidation,
    ElementHasTextValidation,
    ElementHasValueValidation,
    ExtractedCountGteValidation,
    PageTitleContainsValidation,
    NoErrorPageValidation,
    KeyPressSentValidation,
]


# ---------------------------------------------------------------------------
# Action / Validation Results
# ---------------------------------------------------------------------------

class ActionResult(BaseModel):
    """Result of executing a single Playwright action."""
    success: bool = False
    error: Optional[str] = None
    extracted_value: Optional[Any] = None  # For extract actions


class ValidationResult(BaseModel):
    """Result of running a validation rule."""
    passed: bool = False
    error: Optional[str] = None
    detail: str = ""


class PageContext(BaseModel):
    """Snapshot of page state — used when feeding context back to the LLM."""
    url: str = ""
    title: str = ""
    html_snippet: str = ""  # Cleaned HTML (only used for fallback recovery)
    elements_map: str = ""  # Structured map of interactive elements + data (primary LLM input)


# ---------------------------------------------------------------------------
# Browser Step
# ---------------------------------------------------------------------------

class BrowserStep(BaseModel):
    """
    A single step in a browser automation pattern.

    Combines:
    - action: What Playwright should do
    - validation: Deterministic check after the action
    - output_key: Where to store extracted data (for extract actions)
    - audit fields: Tracking failures and AI recoveries
    """
    step_id: str = Field(default_factory=lambda: f"s{uuid.uuid4().hex[:4]}")
    description: str
    action: Dict[str, Any]       # Stored as raw dict for flexible serialization
    validation: Dict[str, Any]   # Stored as raw dict
    output_key: Optional[str] = None   # Key to store extracted data under
    fail_count: int = 0
    ai_recovered: bool = False

    def get_action(self) -> BrowserAction:
        """Parse raw action dict into typed BrowserAction."""
        from pydantic import TypeAdapter
        ta = TypeAdapter(BrowserAction)
        return ta.validate_python(self.action)

    def get_validation(self) -> StepValidation:
        """Parse raw validation dict into typed StepValidation."""
        from pydantic import TypeAdapter
        ta = TypeAdapter(StepValidation)
        return ta.validate_python(self.validation)


# ---------------------------------------------------------------------------
# Browser Pattern (the full saved workflow)
# ---------------------------------------------------------------------------

class BrowserPattern(BaseModel):
    """
    A complete recorded browser automation workflow.

    Stored as JSON on disk at:
        projects/<project_id>/browser_workflows/<fingerprint>.json

    Also referenced in ChromaDB browser_patterns collection for semantic search.
    """
    pattern_id: str = Field(default_factory=lambda: f"bwp_{uuid.uuid4().hex[:8]}")
    project_id: str
    task_summary: str
    fingerprint: str               # Stable keyword-based fingerprint
    url_domain: str = ""           # Primary domain (e.g. "amazon.com")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_run_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_count: int = 0
    ai_recovery_count: int = 0
    variables: List[str] = Field(default_factory=list)  # e.g. ["query", "category"]
    steps: List[BrowserStep] = Field(default_factory=list)

    def touch(self) -> None:
        """Update last_run_at and increment run_count."""
        self.last_run_at = datetime.now(timezone.utc).isoformat()
        self.run_count += 1


# ---------------------------------------------------------------------------
# Replay Result
# ---------------------------------------------------------------------------

class StepAudit(BaseModel):
    """Audit record for a single step during replay."""
    step_id: str
    description: str
    action_type: str
    validation_passed: bool
    ai_recovered: bool = False
    error: Optional[str] = None
    extracted: Optional[Any] = None


class BrowserReplayResult(BaseModel):
    """
    Result returned after a browser replay (or recording) run.

    The extracted_data dict contains all output_key → value mappings
    from extract steps — this is the raw data for report generation.
    """
    success: bool = False
    mode: Literal["replay", "recording"] = "replay"
    pattern_id: str = ""
    cloud_recovery_count: int = 0   # Steps where AI had to fix the action
    cloud_calls: int = 0            # Total AI calls (0 on pure replay)
    step_audit: List[StepAudit] = Field(default_factory=list)
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""               # Human-readable summary for the user
    error: Optional[str] = None
