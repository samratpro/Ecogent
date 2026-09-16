# Ecogent Testing Agent: The Token-Optimized QA Architecture

*Note: This document describes the planned architectural overhaul for the Ecogent Testing Agent, designed to solve token-bloat vulnerabilities and integrate with the Semantic Vector Database.*

---

## 1. The Core Problems with the Current Testing Agent

Currently, the Testing Agent executes Python test functions and returns the raw output directly into the Cloud LLM's context window. This creates major issues:
- **Token Vulnerability:** If a test suite fails and outputs 15,000 lines of error logs, all 15,000 lines are passed to the Cloud LLM. This instantly destroys the context window limit and racks up massive API costs.
- **Framework Blindness:** The agent doesn't intrinsically know how to run tests for a given project (e.g., should it run `pytest`, `npm test`, or `cargo test`?).
- **Execution Blocking:** Running a heavy test suite blocks the entire Ecogent CLI until the tests finish.

---

## 2. The Solution: Semantic Test Maps & Token Safe Guards

To fix this, the new Testing Agent will act as an asynchronous, token-aware test runner backed by **ChromaDB**.

### A. The Semantic Test Map (ChromaDB)
Instead of guessing which test framework to use or where the tests live, the Testing Agent relies on the Semantic JSON Map in ChromaDB.

When a project is created, test suites are registered as metadata:
```json
{
  "test_suite": "User Authentication Tests",
  "test_command": "pytest tests/auth/test_login.py -v",
  "framework": "pytest",
  "dependencies": ["frontend/src/components/LoginButton.tsx"]
}
```

**The Workflow:**
1. **User Request:** *"Run the login tests to see if my button change worked."*
2. **Zero-Cost Retrieval:** The Local Agent queries ChromaDB for "login tests".
3. **Instant Execution:** Chroma returns the exact command (`pytest tests/auth/test_login.py`). The Testing Agent runs the exact command required without burning any LLM tokens to figure out how the project is structured.

### B. Token-Safe Output Truncation
To protect against massive API costs, the Testing Agent implements a strict **Smart Paging & Truncation Layer**.
- If a test output exceeds 2,000 characters, the Agent automatically truncates the middle of the log.
- It returns the *Head* (to show what command ran) and the *Tail* (the actual stack trace where the failure occurred).
- **Result:** The LLM gets exactly the information it needs to fix the bug, while token usage is strictly capped.

### C. Asynchronous Test Execution
Testing will be moved to non-blocking background threads.
- If a test suite takes 5 minutes to run, the Testing Agent pushes it to the background.
- The user can continue chatting with Ecogent or working on other files.
- When the tests finish, the Testing Agent emits a "Test Complete" event with the truncated summary.

---

## 3. Summary of Upgrades

| Feature | Current Testing Agent | Planned Testing Agent (Vector-Backed) |
|---------|-----------------------|---------------------------------------|
| **Test Discovery** | Hardcoded imports | Semantic Map Retrieval (ChromaDB) |
| **Context Protection** | None (Raw strings returned) | Smart Truncation (Caps token usage) |
| **Execution Model** | Blocks main thread | Asynchronous background execution |
| **Framework Support** | Python only | Any language (retrieves command from DB) |
