# Browser Workflow Pattern System — Final Implementation Plan

## Summary of New Requirements

1. **LLM-aware pattern hint**: When the Supervisor fails to parse intent AND a pattern exists in Chroma, pass that hint to the LLM so it never regenerates a new pattern from scratch.
2. **Patterns in ChromaDB**: Browser workflow patterns live in a new Chroma collection `browser_patterns` for semantic retrieval — not just filesystem lookup.
3. **Per-URL pattern isolation**: Same project, different URL/different task → **new pattern**. Same project, same URL/same type of task → **reuse pattern**.
4. **Step-by-step LLM communication on first run**: Recording is interactive — each step is discussed with the LLM before executing.
5. **Strong Playwright action engine**: A dedicated, robust Playwright execution layer for replaying patterns.
6. **Full task routing**: Browser, coding, OS, data — all handled in one clean system.

---

## Complete System Data Flow

```
USER: "go to Amazon, check laptop prices, give me a report"
         │
         ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  execute_local_first()   (local_executor.py)                │
 │                                                             │
 │  1. Supervisor.classify()                                   │
 │     → detects: intent=browser_automation                    │
 │     → complexity=complex → ESCALATE                         │
 │                                                             │
 │  2. Before escalating: CHECK BROWSER PATTERNS (Chroma)      │
 │     → BrowserPatternStore.find_pattern(task, project_id)    │
 │     → Pattern found (distance < 0.35)?                      │
 │          YES ─────────────────────────────────────────────► │
 │          │   BrowserReplayEngine.replay(pattern)            │
 │          │   ├─ Execute Playwright steps                     │
 │          │   ├─ Validate each step (deterministic)          │
 │          │   ├─ Fail? → cloud AI for that step only         │
 │          │   └─ Return extracted data (cloud_calls=0)       │
 │          │                                                   │
 │          NO ──────────────────────────────────────────────► │
 │              CLOUD ESCALATION with pattern hint:             │
 │              "No pattern exists yet for this task.           │
 │               Record steps as you execute them."            │
 │              BrowserRecordingAgent.record_and_execute()     │
 │              ├─ Step 1: Ask LLM → execute → validate        │
 │              ├─ Step 2: Ask LLM → execute → validate        │
 │              ├─ ...                                          │
 │              └─ Save pattern to Chroma + disk               │
 └─────────────────────────────────────────────────────────────┘
```

---

## Part 1: Chroma `browser_patterns` Collection

### What is stored

Each pattern is stored as one Chroma document:

```
ID:       bwp_<fingerprint_hash>          (stable, content-based)
Document: "amazon laptop price compare"  (semantic embedding text)  
Metadata: {
  "project_id":   "proj_abc123",
  "task_summary": "Go to Amazon, search laptops, compare prices",
  "url_domain":   "amazon.com",
  "workflow_file": "projects/proj_abc123/browser_workflows/bwp_xxxx.json",
  "step_count":   5,
  "run_count":    3,
  "last_run_at":  "2026-09-16T06:00:00Z",
  "ai_recovery_count": 1
}
```

### Pattern Matching Logic (No LLM Required)

```
find_pattern(task, project_id):
    1. Extract URL domain from task (if any)  →  "amazon.com"
    2. Query Chroma browser_patterns:
       - semantic distance < 0.35
       - metadata.project_id == project_id
    3. If multiple matches: prefer same url_domain
    4. Return best match or None
```

### Pattern Isolation (Same Chat, Different URL = New Pattern)

```
"go to Amazon, check laptop prices"   →  fingerprint: "amazon laptop price"     → Pattern A
"go to Amazon, compare phone prices"  →  fingerprint: "amazon phone price"       → Pattern B  
"go to eBay, check laptop prices"     →  fingerprint: "ebay laptop price"        → Pattern C
```

The fingerprint combines: `{normalized_domain}_{sorted_action_keywords}`. Two tasks with the same domain AND same core action keywords reuse the same pattern. Different domain OR different action = new pattern.

---

## Part 2: LLM Context Injection (Pattern Hint)

### When Supervisor Fails to Parse Intent

In `execute_local_first()`, before cloud escalation for any browser-like task:

```python
# NEW: Check if a browser pattern already exists
pattern = browser_pattern_store.find_pattern(user_input, project_id)

if pattern:
    # Inject pattern hint into the cloud prompt so LLM never recreates
    cloud_context_hint = (
        f"[SYSTEM NOTE] A recorded browser automation pattern already exists "
        f"for this type of task:\n"
        f"  Pattern ID: {pattern['id']}\n"
        f"  Summary: {pattern['task_summary']}\n"
        f"  Steps recorded: {pattern['step_count']}\n"
        f"  Last run: {pattern['last_run_at']}\n\n"
        f"DO NOT generate a new plan. Instead, confirm you want to reuse "
        f"this pattern and it will be replayed automatically."
    )
```

### When Intent IS Detected as `browser_automation`

If Supervisor detects `browser_automation` + pattern found → skip cloud entirely, go straight to `BrowserReplayEngine`.

If Supervisor detects `browser_automation` + **no pattern** → cloud call with this prompt prefix:

```
[RECORDING MODE] No pattern exists yet for this task.
You will guide a browser automation session step by step.
After each step you propose, the system will execute it and report back.
Then propose the next step. Continue until the task is complete.
At the end, a JSON workflow pattern will be automatically saved.

Task: "{user_input}"

Propose Step 1 now as JSON:
{"action": {"type": "...", ...}, "validation": {"type": "...", ...}, "description": "..."}
```

---

## Part 3: Step-by-Step Recording (First Run)

The recording is **interactive** — LLM proposes one step, Playwright executes it, result is reported back, LLM proposes the next step.

```
LLM → Step 1 JSON → Playwright executes → validate → ✅ → report to LLM
LLM → Step 2 JSON → Playwright executes → validate → ✅ → report to LLM
LLM → Step 3 JSON → Playwright executes → validate → ❌ → report error to LLM
LLM → Step 3 corrected JSON → Playwright executes → validate → ✅ → report to LLM
...
LLM → "Task complete. Here is the final report: ..."
                                                    │
                                                    └─ Save all steps as BrowserPattern JSON
                                                       Register in Chroma browser_patterns
```

### LLM Step Proposal Format

```json
{
  "action": {
    "type": "fill",
    "selector": "#twotabsearchtextbox",
    "value": "gaming laptop"
  },
  "validation": {
    "type": "element_has_value",
    "selector": "#twotabsearchtextbox",
    "value": "gaming laptop"
  },
  "description": "Type search query into Amazon search bar",
  "output_key": null
}
```

### Step Feedback to LLM (After Execution)

```
Step 3 executed. Result:
  Status: ✅ SUCCESS
  Validation: url_contains("field-keywords=") → PASSED
  Page title: "gaming laptop - Amazon Search"
  Extracted: null

Propose Step 4.
```

Or on failure:
```
Step 3 executed. Result:
  Status: ❌ FAILED
  Action: click #nav-search-submit-button
  Error: Element not found (timeout 5000ms)
  Current URL: https://www.amazon.com
  Page title: "Amazon.com"

Correct Step 3 with a different selector or action.
```

---

## Part 4: Playwright Action Engine

### Module: `ecogent_experiment/browser_workflow/playwright_engine.py`

A robust, self-contained Playwright wrapper. All browser operations go through this class.

```python
class PlaywrightEngine:
    """
    Strong, reliable Playwright wrapper for pattern-based browser automation.
    
    Handles:
    - Browser lifecycle (launch, context, page, close)
    - Action execution with retries and timeouts
    - Deterministic validation (no LLM)
    - Variable substitution in step values
    - Screenshot capture on failure (for debugging)
    - Page HTML capture for AI recovery prompts
    """
    
    def execute_action(self, page, action: BrowserAction, variables: dict) -> ActionResult
    def validate_step(self, page, validation: StepValidation, extracted: dict) -> ValidationResult
    def get_page_context(self, page) -> PageContext  # URL, title, HTML snippet for AI recovery
```

### All Action Types (Playwright Implementation)

```python
# navigate
page.goto(url, wait_until="domcontentloaded", timeout=15000)

# click
page.locator(selector).click(timeout=5000)
# With fallback: if CSS selector fails, try text-based locator

# fill
page.locator(selector).clear()
page.locator(selector).fill(value)

# select  
page.locator(selector).select_option(option)

# extract (single)
text = page.locator(selector).inner_text(timeout=5000)

# extract (multiple)
texts = page.locator(selector).all_inner_texts()

# wait_for (element)
page.locator(selector).wait_for(timeout=10000)

# wait_for (time)
page.wait_for_timeout(ms)

# scroll
page.evaluate(f"window.scrollBy(0, {amount})")

# screenshot (for debugging/audit)
page.screenshot(path=output_path)

# key_press
page.keyboard.press(key)   # "Enter", "Tab", etc.
```

### All Validation Types (Deterministic, No LLM)

```python
def validate(page, rule: StepValidation, extracted: dict) -> ValidationResult:
    
    if rule.type == "url_contains":
        return rule.value.lower() in page.url.lower()
    
    elif rule.type == "element_exists":
        return page.locator(rule.selector).count() > 0
    
    elif rule.type == "element_has_text":
        el = page.locator(rule.selector).first
        return rule.text.lower() in el.inner_text().lower()
    
    elif rule.type == "element_has_value":
        return page.locator(rule.selector).input_value() == rule.value
    
    elif rule.type == "extracted_count_gte":
        return len(extracted.get(rule.output_key, [])) >= rule.count
    
    elif rule.type == "page_title_contains":
        return rule.value.lower() in page.title().lower()
    
    elif rule.type == "no_error_page":
        # Check for common error indicators
        error_patterns = ["404", "not found", "error", "page not available"]
        title = page.title().lower()
        return not any(p in title for p in error_patterns)
    
    elif rule.type == "key_press_sent":
        return True  # Key press actions self-validate
```

---

## Part 5: Full Task Routing (All Task Types)

The existing Supervisor already handles: `file_operation`, `data_processing`, `system_info`, `testing`, `browsing`, `code_generation`.

This feature adds `browser_automation`. Here is the **complete routing table**:

| Intent | Tool | Agent | Cloud? | Browser Pattern? |
|---|---|---|---|---|
| `file_operation` | `read_file`, `write_file`, etc. | `os_agent` | No | No |
| `data_processing` | `read_csv`, `calculate_statistics`, etc. | `os_agent` | No | No |
| `system_info` | `system_info` | `os_agent` | No | No |
| `testing` | `run_python_test` | `testing_agent` | No | No |
| `browsing` | `web_search`, `browse_website` | `browser_agent` | No | No |
| `code_generation` | — | `coding_agent` | **YES** | No |
| **`browser_automation`** | **`browser_task`** | **`browser_agent`** | **Only 1st run** | **YES** |
| `unknown` complex | — | — | **YES** | Checked first |

### New Supervisor Rules (browser_automation)

```python
# Multi-step browser automation — navigate AND interact
(re.compile(
    r"\b(go\s+to|navigate\s+to|open\s+site|visit)\b.{0,80}"
    r"\b(and|then)\b.{0,80}"
    r"\b(click|check|compare|search|buy|add|fill|select|price|product|login|signup|submit|form)\b",
    re.I | re.S
), "browser_automation", "browser_task", "browser_agent", "complex"),

# Explicit browser task commands
(re.compile(
    r"\b(automate|browser\s*task|browser\s*workflow|interact\s+with\s+site|fill\s+out\s+form)\b",
    re.I
), "browser_automation", "browser_task", "browser_agent", "complex"),

# Repeated task phrase detection
(re.compile(
    r"\b(do\s+the\s+same|same\s+task|repeat\s+(that|this|it)|do\s+it\s+again|run\s+again)\b",
    re.I
), "browser_automation", "browser_task", "browser_agent", "complex"),
```

### Updated `execute_local_first()` Hook

```python
# After Supervisor classifies, BEFORE cloud escalation check:
if decision.intent == "browser_automation" or _looks_like_browser_task(user_input):
    
    # Check Chroma for existing pattern (project-scoped)
    browser_pattern_store = BrowserPatternStore(chroma_dir, project_id)
    pattern = browser_pattern_store.find_pattern(user_input)
    
    if pattern:
        # REPLAY PATH — 0 cloud calls
        result.execution_path.append("browser_replay")
        replay_result = BrowserReplayEngine(cloud_provider).replay(
            pattern=pattern,
            variables={},
            ask_llm=ask_llm_fn,
        )
        result.output = replay_result.summary
        result.cloud_llm_calls = replay_result.cloud_recovery_count
        result.success = replay_result.success
        return result
    
    else:
        # RECORDING PATH — inject into cloud escalation context
        result.cloud_escalated = True
        result.cloud_escalation_context = {
            "mode": "browser_recording",
            "project_id": project_id,
            "task": user_input,
        }
        return result
```

---

## Files to Create / Modify

### New Files

| File | Purpose |
|---|---|
| `ecogent_experiment/browser_workflow/__init__.py` | Package init |
| `ecogent_experiment/browser_workflow/schema.py` | Pydantic models: `BrowserAction`, `StepValidation`, `BrowserStep`, `BrowserPattern`, `BrowserReplayResult` |
| `ecogent_experiment/browser_workflow/fingerprint.py` | `task_to_fingerprint()`, `extract_url_domain()` |
| `ecogent_experiment/browser_workflow/pattern_store.py` | `BrowserPatternStore` — Chroma CRUD for `browser_patterns` collection |
| `ecogent_experiment/browser_workflow/playwright_engine.py` | `PlaywrightEngine` — all Playwright action + validation methods |
| `ecogent_experiment/browser_workflow/recorder.py` | `BrowserRecordingAgent` — step-by-step LLM + Playwright recording |
| `ecogent_experiment/browser_workflow/replayer.py` | `BrowserReplayEngine` — deterministic replay with AI recovery |
| `ecogent_experiment/browser_workflow/manager.py` | `BrowserWorkflowManager` — orchestrator entry point |
| `tools/builtin/browser_automation.py` | `browser_task()` builtin tool function |

### Modified Files

| File | Change |
|---|---|
| `ecogent_experiment/supervisor.py` | Add 3 new `browser_automation` rules |
| `ecogent_experiment/local_executor.py` | Add browser pattern intercept before cloud escalation |
| `ecogent_experiment/tool_registry.py` | Add `browser_patterns` to `COLLECTIONS` list + CRUD methods |
| `ecogent_experiment/agents/browser_agent.py` | Add `browser_task` dispatch at top of `execute()` |
| `ecogent_experiment/lc_tools.py` | Register `browser_task` as `EcogentTool` |
| `ecogent_experiment/cli.py` | Pass `project_id` + `cloud_escalation_context` to recording agent when `mode=browser_recording` |
| `bootstrap.py` | Add `browser_patterns` Chroma collection + `browser_task` to tool list + Playwright install note |
| `requirements.txt` | Add `playwright>=1.40.0` |

---

## `BrowserPatternStore` (Chroma Integration Detail)

```python
class BrowserPatternStore:
    """Manages browser workflow patterns in ChromaDB browser_patterns collection."""
    
    COLLECTION = "browser_patterns"
    MATCH_DISTANCE_THRESHOLD = 0.35  # < this = reuse pattern
    
    def find_pattern(self, task: str) -> Optional[dict]:
        """Semantic search in Chroma, filtered to this project_id."""
    
    def save_pattern(self, pattern: BrowserPattern) -> bool:
        """Upsert pattern into Chroma. ID = fingerprint hash."""
    
    def update_pattern(self, pattern_id: str, updates: dict) -> bool:
        """Update run_count, last_run_at, ai_recovery_count after replay."""
    
    def get_pattern_by_id(self, pattern_id: str) -> Optional[BrowserPattern]:
        """Load full pattern JSON from disk using metadata.workflow_file."""
    
    def list_project_patterns(self) -> list[dict]:
        """List all patterns for this project (for CLI inspect command)."""
```

---

## Pattern JSON on Disk

Location: `projects/<project_id>/browser_workflows/<fingerprint>.json`

```json
{
  "pattern_id": "bwp_a3f2c1d4",
  "project_id": "proj_abc123",
  "task_summary": "Go to Amazon, search laptops, compare prices",
  "fingerprint": "amazon laptop price",
  "url_domain": "amazon.com",
  "created_at": "2026-09-16T06:00:00Z",
  "last_run_at": "2026-09-16T07:30:00Z",
  "run_count": 3,
  "ai_recovery_count": 1,
  "variables": ["query"],
  "steps": [
    {
      "step_id": "s1",
      "description": "Navigate to Amazon",
      "action": {"type": "navigate", "url": "https://www.amazon.com"},
      "validation": {"type": "url_contains", "value": "amazon.com"},
      "output_key": null,
      "fail_count": 0,
      "ai_recovered": false
    },
    {
      "step_id": "s2",
      "description": "Fill search box",
      "action": {"type": "fill", "selector": "#twotabsearchtextbox", "value": "{query}"},
      "validation": {"type": "element_has_value", "selector": "#twotabsearchtextbox", "value": "{query}"},
      "output_key": null,
      "fail_count": 0,
      "ai_recovered": false
    },
    {
      "step_id": "s3",
      "description": "Submit search",
      "action": {"type": "key_press", "key": "Enter"},
      "validation": {"type": "url_contains", "value": "field-keywords="},
      "output_key": null,
      "fail_count": 1,
      "ai_recovered": true
    },
    {
      "step_id": "s4",
      "description": "Extract product titles",
      "action": {"type": "extract", "selector": "h2.a-size-mini a span", "multiple": true},
      "validation": {"type": "extracted_count_gte", "count": 1},
      "output_key": "titles",
      "fail_count": 0,
      "ai_recovered": false
    },
    {
      "step_id": "s5",
      "description": "Extract product prices",
      "action": {"type": "extract", "selector": ".a-price-whole", "multiple": true},
      "validation": {"type": "extracted_count_gte", "count": 1},
      "output_key": "prices",
      "fail_count": 0,
      "ai_recovered": false
    }
  ]
}
```

---

## CLI Output Examples

### First Run (Recording)
```
─────────────────────────────────────
[ECOGENT ROUTER]
  Request: "go to Amazon, check gaming laptop prices"
  ✓ Local Supervisor: intent=browser_automation, complexity=complex
  ✓ Chroma [browser_patterns]: No matching pattern found (project: proj_abc123)
  ↑ CLOUD ESCALATION: browser_recording_mode
  [🎬 BROWSER RECORDING] Communicating with AI step-by-step...
  Step 1/?: Navigate to Amazon → ✅
  Step 2/?: Fill search box → ✅
  Step 3/?: Submit search → ❌ → AI recovery → ✅ (selector updated)
  Step 4/?: Extract titles → ✅
  Step 5/?: Extract prices → ✅
  AI: "Task complete."
  [💾 PATTERN SAVED] bwp_a3f2c1d4 (5 steps) → Chroma + disk
  Cloud LLM calls: 7 | Tiny LLM: 0 | Local tool: 0
```

### Second Run (Replay — Same Chat)
```
─────────────────────────────────────
[ECOGENT ROUTER]
  Request: "go to Amazon, check gaming laptop prices again"
  ✓ Local Supervisor: intent=browser_automation, complexity=complex
  ✓ Chroma [browser_patterns]: Pattern bwp_a3f2c1d4 matched (distance: 0.12)
  [▶ BROWSER REPLAY] Executing 5 steps without AI...
  Step 1/5: Navigate → ✅
  Step 2/5: Fill search → ✅
  Step 3/5: Submit → ✅
  Step 4/5: Extract titles → ✅ (12 items)
  Step 5/5: Extract prices → ✅ (12 items)
  Cloud LLM calls: 0 | Tiny LLM: 0 | Local tool: 5
```

### Different Task Same Chat (New Pattern)
```
  Request: "go to Amazon and check phone prices"
  ✓ Chroma [browser_patterns]: No match (closest: amazon laptop price, distance: 0.61)
  ↑ CLOUD ESCALATION: browser_recording_mode (new pattern will be created)
```

---

## Verification Plan

### Tests
```
tests/test_browser_pattern_store.py   — Chroma save/find/update
tests/test_browser_fingerprint.py     — Fingerprint collision/isolation
tests/test_playwright_engine.py       — Action/validation with mock page
tests/test_browser_recorder.py        — Step-by-step recording flow (mock LLM)
tests/test_browser_replayer.py        — Replay with injected failures
```

### Manual
1. **First run** → verify Chroma has 1 entry in `browser_patterns`, JSON file on disk.
2. **Repeat run** → verify `cloud_llm_calls=0` in console metrics.
3. **Different URL same chat** → verify new pattern created, old pattern untouched.
4. **Corrupt a step selector** → verify AI recovery fires, selector updated in JSON.
5. **Coding task in same chat** → verify normal cloud path, no browser pattern lookup.
