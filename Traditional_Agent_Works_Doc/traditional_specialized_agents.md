# Traditional Agent Specialized Roles: OS Agent, Browser Agent, Code Agent, and Testing Agent

## 1. Purpose

Modern agent systems often divide a large task into specialized capabilities rather than asking one generic agent to perform every operation.

A useful conceptual decomposition is:

```text
                         User Task
                            ↓
                     Supervisor / Router
                            ↓
        ┌───────────────────┼───────────────────┐
        ↓                   ↓                   ↓
    Code Agent          Browser Agent       OS Agent
        ↓                   ↓                   ↓
   Code Tools           Web Tools          Computer Tools
        │                   │                   │
        └───────────────────┼───────────────────┘
                            ↓
                       Testing Agent
                            ↓
                         Results
```

These roles should not be treated as universal industry standards. Different systems use different names, boundaries, and combinations. For example, OpenHands documents an agent architecture centered on a reasoning-action loop, tools, context management, workspaces, and security validation. citeturn0search0

The four roles are useful for understanding an agent architecture like **Ecogent**:

- **Code Agent** — works with source code and repositories.
- **Browser Agent** — interacts with websites/web applications.
- **OS Agent** — operates a computer/desktop environment.
- **Testing Agent** — validates whether the task or modification works correctly.

---

# 2. Important Architectural Principle

These are **specialized agents**, not necessarily four independent LLMs.

A system can implement them using:

### Option A — One LLM, different toolsets

```text
                    One LLM
                       ↓
                Agent Controller
                       ↓
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
   Code Tools     Browser Tools    OS Tools
                       ↓
                 Testing Tools
```

### Option B — Multiple specialized agents

```text
                 Supervisor
                     ↓
       ┌─────────────┼─────────────┐
       ↓             ↓             ↓
   Code Agent   Browser Agent   OS Agent
       ↓             ↓             ↓
     LLM-A          LLM-B         LLM-C
                     ↓
               Testing Agent
```

### Option C — Hybrid

```text
Tiny Supervisor
      ↓
Specialized Agent
      ↓
Shared Reasoning LLM
      ↓
Specialized Tools
```

For a cost-aware architecture, the third approach is especially interesting because the supervisor does not necessarily need to be a large reasoning model.

---

# 3. Generic Agent Architecture

A specialized agent can be modeled as:

```text
                  Agent
                    │
       ┌────────────┼────────────┐
       ↓            ↓            ↓
    Context       Tools        State
       │            │            │
       └────────────┼────────────┘
                    ↓
                   LLM
                    ↓
                 Action
                    ↓
               Tool Runtime
                    ↓
                Observation
                    ↓
              State Update
                    ↓
                   LLM
```

The core loop remains:

```text
Observe
   ↓
Reason
   ↓
Act
   ↓
Observe
   ↓
Reason
   ↓
Act
```

This is closely related to the ReAct reasoning/action pattern.

---

# 4. Code Agent

## 4.1 What is a Code Agent?

A **Code Agent** is an agent specialized in software-engineering tasks.

Typical responsibilities include:

```text
Understand repository
        ↓
Search source code
        ↓
Read relevant files
        ↓
Reason about implementation
        ↓
Modify files
        ↓
Run tests / programs
        ↓
Inspect errors
        ↓
Modify again
        ↓
Verify
```

A major research reference is **SWE-agent**, which studies how language-model agents can use specially designed agent-computer interfaces for software engineering. The system provides capabilities for creating/editing code, navigating repositories, and executing tests/programs. citeturn0academia62

---

# 5. Code Agent Toolset

A typical code agent may have tools such as:

```text
list_directory()
read_file()
search_code()
search_files()
create_file()
edit_file()
delete_file()
move_file()
run_command()
run_tests()
git_diff()
git_status()
```

Example registry:

```python
code_tools = [
    "list_directory",
    "read_file",
    "search_code",
    "edit_file",
    "run_command",
    "run_tests",
    "git_diff"
]
```

The LLM sees tool descriptions/schemas, while the runtime contains the actual implementations.

---

# 6. Code Agent Example

User:

```text
Add email-based authentication to my Django project.
```

A possible trajectory:

```text
User Request
     ↓
Code Agent
     ↓
search_code("authentication")
     ↓
Observation
     ↓
read_file("settings.py")
     ↓
Observation
     ↓
read_file("models.py")
     ↓
Observation
     ↓
Reason
     ↓
edit_file("models.py")
     ↓
Observation
     ↓
edit_file("settings.py")
     ↓
Observation
     ↓
run_tests()
     ↓
Test Result
     ↓
Fix if necessary
     ↓
Final Result
```

The agent does not need to know the complete repository beforehand.

It can discover the relevant files through tools.

---

# 7. Code Agent State

A useful state representation is:

```json
{
  "goal": "Implement email authentication",
  "repository": "/workspace/project",
  "files_modified": [
    "userapp/models.py",
    "settings.py"
  ],
  "tests_run": [
    "pytest"
  ],
  "test_status": "passed"
}
```

This is different from raw conversation history.

The structured state records information that is useful for continuing the task.

---

# 8. Code Agent and Repository as Environment

For software agents, the repository itself acts as an important external environment.

```text
             Code Agent
                  ↓
       ┌──────────┴──────────┐
       ↓                     ↓
   Repository             Runtime
       ↓                     ↓
 source files            commands/tests
       ↓                     ↓
   observations          observations
```

This is important because the current filesystem can be more authoritative than an old conversation statement.

For example:

```text
Previous conversation:
"login.py contains the login function."

Current repository:
login.py was renamed to auth/views.py.
```

The agent should inspect the current repository rather than blindly trusting the old statement.

---

# 9. Browser Agent

## 9.1 What is a Browser Agent?

A **Browser Agent** is specialized in interacting with websites and web applications.

Typical capabilities include:

```text
Open webpage
      ↓
Observe page
      ↓
Find relevant element
      ↓
Click
      ↓
Type
      ↓
Submit
      ↓
Observe result
      ↓
Continue
```

BrowserGym is a research ecosystem for web-agent research. It provides standardized environments, observations, and action spaces for evaluating agents interacting with web environments. citeturn0academia60

---

# 10. Browser Agent Tools

Typical browser tools include:

```text
open_page(url)
click(element)
type(element, text)
select_option(element, value)
press_key(key)
scroll(direction)
go_back()
extract_text()
take_screenshot()
get_dom()
```

A browser agent may receive different observations:

```text
HTML / DOM
Accessibility tree
Screenshot
Visible text
URL
Page metadata
```

The exact representation depends on the browser environment.

---

# 11. Browser Agent Example

User:

```text
Find the price of a specific laptop on a website.
```

Possible trajectory:

```text
User
 ↓
Browser Agent
 ↓
open_page("example.com")
 ↓
Observation: homepage
 ↓
search_box(...)
 ↓
type("laptop model")
 ↓
click(search)
 ↓
Observation: search results
 ↓
click(product)
 ↓
Observation: product page
 ↓
extract_text()
 ↓
Observation: price
 ↓
Final Answer
```

The agent continuously converts browser observations into the next action.

---

# 12. Browser Agent Has a Different Environment

The Code Agent primarily interacts with:

```text
Filesystem
Source code
Terminal
Compiler
Test runner
Git
```

The Browser Agent primarily interacts with:

```text
Webpage
DOM
Accessibility tree
Browser state
Network-backed application
Forms
Buttons
Links
```

Therefore, the same LLM can require very different tools and context depending on the environment.

---

# 13. OS Agent

## 13.1 What is an OS Agent?

An **OS Agent** or computer-use agent operates a real or virtual desktop environment.

It can interact with:

```text
Desktop
Windows
Applications
Files
Menus
Dialogs
Keyboard
Mouse
Clipboard
System settings
```

OSWorld is a major benchmark for this type of agent. It evaluates multimodal agents on real computer environments including operating systems such as Ubuntu, Windows, and macOS, with tasks involving web/desktop applications, file I/O, and multi-application workflows. citeturn0search2turn0search6

---

# 14. OS Agent Tools

A simplified OS toolset could include:

```text
click(x, y)
double_click(x, y)
type_text(text)
press_key(key)
hotkey(...)
move_mouse(x, y)
scroll(...)
take_screenshot()
open_application(name)
read_clipboard()
write_clipboard(text)
execute_shell(command)
```

Computer-use systems may instead expose higher-level actions such as:

```text
computer.click()
computer.type()
computer.key()
computer.screenshot()
```

---

# 15. OS Agent Observation

An OS agent may observe:

```text
Screenshot
Accessibility tree
Window information
Cursor position
Clipboard
Application state
Filesystem state
```

For example:

```text
Screenshot
   ↓
Vision / grounding
   ↓
LLM
   ↓
Click(x=650, y=420)
   ↓
New screenshot
   ↓
LLM
```

This is different from a text-only coding agent.

---

# 16. OS Agent Example

User:

```text
Open LibreOffice, create a document, write the report, and save it as PDF.
```

Trajectory:

```text
OS Agent
   ↓
observe_screen()
   ↓
Observation: desktop visible
   ↓
open_application("LibreOffice")
   ↓
Observation: LibreOffice opened
   ↓
click("Writer")
   ↓
Observation: Writer opened
   ↓
type_text(report)
   ↓
hotkey("CTRL+SHIFT+S")
   ↓
Observation: Save dialog
   ↓
type_text(filename)
   ↓
press_key("ENTER")
   ↓
Observation: file saved
```

The agent must continuously verify that the expected UI state actually occurred.

---

# 17. Why OS Agents Are More Difficult

OS agents operate in a highly dynamic environment.

For example:

```text
Expected:
Click Save

Actual:
Dialog appeared
```

or:

```text
Expected:
Application opened

Actual:
Application is still loading
```

Therefore, the agent needs:

```text
Observation
 ↓
State understanding
 ↓
Action
 ↓
Verification
```

rather than blindly executing a fixed sequence.

OSWorld research demonstrates that real computer-use tasks remain challenging because agents must deal with GUI grounding and operational knowledge across diverse applications. citeturn0academia59

---

# 18. Testing Agent

## 18.1 What is a Testing Agent?

A **Testing Agent** is specialized in verifying whether an implementation or workflow satisfies the expected requirements.

It can perform:

```text
Run tests
 ↓
Inspect failures
 ↓
Understand failure
 ↓
Locate cause
 ↓
Suggest or implement fix
 ↓
Run tests again
```

A testing agent is therefore not necessarily limited to pressing a "Run Tests" button.

It can reason about test results.

---

# 19. Testing Agent Tools

Typical tools:

```text
run_tests()
run_unit_tests()
run_integration_tests()
run_linter()
run_type_checker()
run_build()
inspect_test_output()
read_test_file()
generate_test()
```

Example:

```text
Testing Agent
      ↓
run_tests()
      ↓
Failure
      ↓
inspect_test_output()
      ↓
read_file()
      ↓
Reason
      ↓
Report / send to Code Agent
```

---

# 20. Testing Agent Example

Suppose the Code Agent changed:

```text
userapp/views.py
```

The Testing Agent receives:

```text
Task:
Verify email login.
```

It might perform:

```text
run_tests("authentication")
        ↓
FAIL
        ↓
inspect_test_output()
        ↓
"Invalid credentials"
        ↓
read_file("backends.py")
        ↓
Reason
        ↓
Test again
```

If the failure is caused by implementation code, the Testing Agent can hand the issue back to the Code Agent.

---

# 21. Code Agent + Testing Agent

This is an important multi-agent pattern:

```text
             Supervisor
                  ↓
             Code Agent
                  ↓
              Edit Code
                  ↓
            Testing Agent
                  ↓
              Run Tests
             /          \
          PASS           FAIL
           ↓               ↓
         Finish       Code Agent
                          ↓
                       Fix Code
                          ↓
                    Testing Agent
```

This creates a feedback loop:

```text
Code → Test → Failure → Code → Test → ...
```

This pattern is especially useful for software engineering agents.

---

# 22. Browser Agent + Testing Agent

The same concept works for web applications.

```text
Code Agent
    ↓
Modify web application
    ↓
Browser Agent
    ↓
Open application
    ↓
Perform user workflow
    ↓
Testing Agent
    ↓
Validate expected result
```

For example:

```text
Code Agent:
Implement registration.

Browser Agent:
Open /register
Fill form
Submit

Testing Agent:
Verify activation email / success state
```

---

# 23. OS Agent + Browser Agent

These roles can overlap.

For example:

```text
OS Agent
 ↓
Open Chrome
 ↓
Browser Agent
 ↓
Navigate website
 ↓
Browser Agent
 ↓
Perform web actions
 ↓
OS Agent
 ↓
Download file
 ↓
OS filesystem
```

The boundary is therefore architectural rather than absolute.

A single computer-use agent may expose both browser-level and OS-level capabilities.

---

# 24. All Four Agents Together

A complex software task could use:

```text
                         User
                           ↓
                     Supervisor
                           ↓
              ┌────────────┼────────────┐
              ↓            ↓            ↓
          Code Agent   Browser Agent  OS Agent
              ↓            ↓            ↓
          Source Code     Web App      Desktop
              │            │            │
              └────────────┼────────────┘
                           ↓
                     Testing Agent
                           ↓
                       Validation
                           ↓
                         Result
```

But the supervisor does not necessarily call every agent.

It should route only the required work.

---

# 25. Example: Build a Django SaaS Feature

User:

```text
Add registration, email activation, and password reset
to my Django SaaS project and verify everything.
```

### Step 1 — Supervisor

```text
Detect:
software engineering task

Required capabilities:
Code Agent
Testing Agent
possibly Browser Agent
```

### Step 2 — Code Agent

```text
Inspect project
 ↓
Inspect custom user model
 ↓
Inspect URLs
 ↓
Inspect settings
 ↓
Implement registration
 ↓
Implement activation
 ↓
Implement password reset
```

### Step 3 — Testing Agent

```text
Run unit tests
 ↓
Run integration tests
 ↓
Find failures
```

### Step 4 — Browser Agent

```text
Open registration page
 ↓
Submit registration
 ↓
Verify activation flow
 ↓
Verify password reset flow
```

### Step 5 — Code Agent

If browser testing discovers a bug:

```text
Browser observation
 ↓
Testing result
 ↓
Code Agent
 ↓
Fix
 ↓
Testing Agent
 ↓
Verify
```

---

# 26. Agent-to-Agent Communication

Agents need structured outputs.

Instead of:

```text
"Something is broken."
```

A better result is:

```json
{
  "status": "failed",
  "task": "email_activation",
  "error": "Activation token rejected",
  "file": "userapp/views.py",
  "line": 142,
  "evidence": "HTTP 400",
  "suggested_next_agent": "code_agent"
}
```

This allows the supervisor to route the result.

---

# 27. Shared State

A multi-agent system should have a shared task state.

Example:

```json
{
  "task_id": "task_001",
  "goal": "Implement email activation",
  "status": "testing",
  "current_agent": "testing_agent",
  "modified_files": [
    "userapp/models.py",
    "userapp/views.py",
    "settings.py"
  ],
  "test_status": "failed",
  "last_error": "Activation token rejected"
}
```

This is more useful than forcing every agent to reconstruct the entire conversation.

---

# 28. Agent Handoff

A common architecture is:

```text
Agent A
   ↓
Structured Result
   ↓
Supervisor
   ↓
Agent B
```

Example:

```text
Browser Agent
      ↓
{
  "bug": "Registration form returns HTTP 500"
}
      ↓
Supervisor
      ↓
Code Agent
      ↓
Inspect registration view
```

The supervisor decides which capability should handle the next step.

---

# 29. Specialized Agent vs Tool

This distinction is extremely important.

A **tool** normally performs a relatively specific operation:

```text
read_file()
click()
run_tests()
search_web()
```

An **agent** can decide which tools to use and in what order.

For example:

```text
Code Agent
   ↓
search_code()
   ↓
read_file()
   ↓
edit_file()
   ↓
run_tests()
```

The Code Agent is therefore a reasoning/controller layer over multiple tools.

---

# 30. Agent vs Tool Hierarchy

```text
Supervisor
    ↓
Specialized Agent
    ↓
Tool Selection
    ↓
Tool Execution
```

For example:

```text
Supervisor
   ↓
Code Agent
   ↓
┌───────────────┐
│ search_code   │
│ read_file     │
│ edit_file     │
│ run_command   │
│ run_tests     │
└───────────────┘
```

---

# 31. Why Specialization Helps

Different environments expose different tool schemas.

### Code Agent

```text
read_file
edit_file
search_code
run_tests
git_diff
```

### Browser Agent

```text
open_page
click
type
scroll
extract_text
screenshot
```

### OS Agent

```text
click
type
keypress
screenshot
open_application
clipboard
```

### Testing Agent

```text
run_tests
run_linter
run_build
inspect_failure
generate_test
```

Instead of showing all tools to every model call, a supervisor can retrieve/select the relevant capability.

This is directly relevant to your **semantic tool retrieval** research.

---

# 32. Tool Selection Problem

Suppose the global registry contains:

```text
500 tools
```

A generic LLM could receive all 500 tool schemas.

That can increase:

```text
Context size
+
Input tokens
+
Tool-selection complexity
```

A specialized architecture could first determine:

```text
Task:
Fix Django authentication
```

Then retrieve:

```text
Code Agent
```

and expose only:

```text
read_file
search_code
edit_file
run_tests
```

This is a potential cost/context optimization.

---

# 33. Your Ecogent Architecture

Your proposed architecture can therefore be represented as:

```text
                         User
                           ↓
                  Tiny Local Supervisor
                           ↓
                    Intent Detection
                           ↓
                 Workflow Retrieval
                           ↓
                Specialized Agent
                           ↓
          ┌────────────────┼────────────────┐
          ↓                ↓                ↓
      Code Agent       Browser Agent     OS Agent
          ↓                ↓                ↓
       Tools            Tools            Tools
          └────────────────┼────────────────┘
                           ↓
                    Testing Agent
                           ↓
                    Workflow Update
                           ↓
                  Semantic Memory
                           ↓
                    Next Context
```

The supervisor does not need to perform the actual work.

It routes the task.

---

# 34. Local Tiny Supervisor

For your cost-aware thesis, a small local model could perform:

```text
Input:
"Fix the broken login test."

Supervisor output:

{
  "agent": "code_agent",
  "reason": "software modification",
  "tools": [
    "search_code",
    "read_file",
    "edit_file",
    "run_tests"
  ]
}
```

Then the larger reasoning model is used only where necessary.

This is a research design choice and should be experimentally evaluated rather than assumed to reduce total cost.

---

# 35. Semantic Tool Retrieval

Your architecture can additionally retrieve tools semantically.

Example:

```text
User:
"Find why the login test fails."

        ↓

Semantic Retrieval
        ↓

Relevant tool schemas:

search_code
read_file
run_tests
read_test_output
```

Instead of:

```text
All tools:
500 tools
```

The context becomes:

```text
4 relevant tools
```

This gives you a clear experimental variable:

```text
All Tools
     vs
Retrieved Tools
```

---

# 36. Workflow Retrieval

The same idea can be applied to previous workflows.

Current task:

```text
"Fix email activation failure."
```

FAISS retrieval might find:

```text
Workflow #41:
Django email activation implementation

Workflow #92:
Activation token debugging

Workflow #113:
Password reset email configuration
```

The system can retrieve the relevant workflow state.

Conceptually:

```text
Current Task
    ↓
Embedding
    ↓
FAISS
    ↓
Relevant Workflow IDs
    ↓
Load structured workflow JSON
    ↓
Build context
```

Important:

> FAISS should be treated as the semantic retrieval/index layer; the authoritative workflow data can remain in JSON, SQLite, PostgreSQL, or another persistent store.

---

# 37. Traditional Agent vs Ecogent

| Feature | Traditional Specialized Agent | Ecogent Proposal |
|---|---|---|
| Supervisor | Optional | Explicit |
| Agent specialization | Common design pattern | Core architecture |
| Tool registry | Usually available | Registry + semantic retrieval |
| Tool selection | LLM/tool schema | Retrieval + LLM |
| State | Runtime/session state | Structured workflow state |
| Memory | Optional | Explicit workflow memory |
| Semantic retrieval | Optional | Core research component |
| Local supervisor | Not required | Proposed |
| Workflow reuse | Possible | Core objective |
| Cost optimization | Usually secondary | Central research objective |

This comparison is conceptual. There is no single architecture shared by all traditional agents.

---

# 38. How the Agents Work Together

A useful end-to-end model is:

```text
                    USER
                      ↓
                 SUPERVISOR
                      ↓
                Understand Task
                      ↓
             Retrieve Workflow
                      ↓
            Retrieve Relevant Tools
                      ↓
              Select Agent
                      ↓
        ┌─────────────┴─────────────┐
        ↓                           ↓
   CODE AGENT                  BROWSER AGENT
        ↓                           ↓
   Source tools                 Web tools
        ↓                           ↓
        └─────────────┬─────────────┘
                      ↓
                  OS AGENT
                      ↓
                 OS tools
                      ↓
               TESTING AGENT
                      ↓
                 Validation
                      ↓
                Update State
                      ↓
              Store Workflow
                      ↓
                Final Result
```

---

# 39. Important Boundary: Testing Agent

The Testing Agent should not necessarily modify code.

A cleaner architecture is:

```text
Code Agent
   ↓
Implementation
   ↓
Testing Agent
   ↓
Validation
   ↓
PASS → Finish
FAIL → Supervisor → Code Agent
```

This separation can make evaluation easier.

However, an implementation can combine coding and testing into a single agent if desired.

---

# 40. Evaluation Opportunities

For your thesis, each specialized agent can have separate measurements.

### Code Agent

```text
Task success
Patch correctness
Tests passed
Number of tool calls
LLM calls
Tokens
Latency
```

### Browser Agent

```text
Task completion
Action count
Page errors
Navigation failures
Tokens
Latency
```

### OS Agent

```text
Task success
GUI actions
Step count
Recovery attempts
Tokens
Latency
```

### Testing Agent

```text
Bug detection
False positives
False negatives
Tests executed
Verification success
Tokens
Latency
```

---

# 41. Multi-Agent Cost Measurement

Your thesis can measure:

```text
Total Cost =
Supervisor Cost
+
Agent Reasoning Cost
+
Tool/Execution Cost
+
Retrieval Cost
```

For LLM usage:

```text
Total LLM Calls =
Supervisor Calls
+
Code Agent Calls
+
Browser Agent Calls
+
OS Agent Calls
+
Testing Agent Calls
```

And:

```text
Total Tokens =
Input Tokens
+
Output Tokens
```

These metrics allow comparison against a single-agent baseline.

---

# 42. Important Baselines

A strong experiment could compare:

### Baseline A — Single Agent

```text
User
 ↓
One LLM
 ↓
All tools
 ↓
Task
```

### Baseline B — ReAct Agent

```text
User
 ↓
LLM
 ↓
Reason → Act → Observe
```

### Baseline C — Specialized Agents

```text
User
 ↓
Supervisor
 ↓
Specialized Agent
 ↓
Tools
```

### Proposed — Ecogent

```text
User
 ↓
Tiny Supervisor
 ↓
Workflow Retrieval
 ↓
Tool Retrieval
 ↓
Specialized Agent
 ↓
Tools
 ↓
Structured Workflow Update
```

This gives you a meaningful experimental progression.

---

# 43. Key Research Hypothesis

A precise hypothesis could be:

> **H1:** Semantic retrieval of relevant workflows and tools can reduce LLM context size and token consumption while maintaining comparable task success to a baseline agent that receives the full available workflow/tool context.

Possible secondary hypotheses:

> **H2:** Specialized agent routing can reduce unnecessary tool exposure and tool-selection overhead.

> **H3:** Structured workflow state can reduce repeated transmission of historical execution context.

> **H4:** A lightweight local supervisor can perform task routing with lower computational cost than using a large reasoning model for every routing decision.

These are hypotheses to test, not predetermined conclusions.

---

# 44. Primary References

## SWE-agent

Yang, J., Jimenez, C. E., Wettig, A., Lieret, K., Yao, S., Narasimhan, K., & Press, O. (2024).

*SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering.*

arXiv:2405.15793.

https://arxiv.org/abs/2405.15793

The paper is particularly relevant for the **Code Agent** because it studies specialized interfaces that allow language-model agents to navigate repositories, edit files, and execute tests/programs. citeturn0academia62

---

# 45. BrowserGym

Le Sellier De Chezelles, T., et al. (2024).

*The BrowserGym Ecosystem for Web Agent Research.*

arXiv:2412.05467.

https://arxiv.org/abs/2412.05467

BrowserGym provides environments and standardized observation/action spaces for web-agent research and evaluation. citeturn0academia60

---

# 46. OSWorld

Xie, T., Zhang, D., Chen, J., et al. (2024).

*OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments.*

arXiv:2404.07972.

https://arxiv.org/abs/2404.07972

Project:

https://os-world.github.io/

OSWorld evaluates agents operating real desktop environments and applications across operating systems. citeturn0search2turn0search6

---

# 47. OpenHands Agent Architecture

OpenHands documents an agent architecture with:

- reasoning-action loop
- tool orchestration
- context management
- security validation
- workspaces
- event/state handling

Agent architecture:

https://github.com/OpenHands/docs/blob/main/sdk/arch/agent.mdx

The documentation specifically describes a loop in which the LLM generates tool calls, the runtime converts and validates actions, tools execute, and observations are returned to the agent. citeturn0search0

OpenHands SDK:

https://github.com/OpenHands/software-agent-sdk

The SDK provides agents, tools, workspaces, conversations, events, and agent-server functionality. citeturn0search5turn0search7

---

# 48. ReAct

Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023).

*ReAct: Synergizing Reasoning and Acting in Language Models.*

ICLR 2023.

https://arxiv.org/abs/2210.03629

ReAct provides the foundational reasoning/action/observation pattern used to explain the iterative loop of these agent architectures.

---

# 49. Citation-Ready BibTeX

```bibtex
@article{yang2024sweagent,
  title={SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering},
  author={Yang, John and Jimenez, Carlos E. and Wettig, Alexander and Lieret, Kilian and Yao, Shunyu and Narasimhan, Karthik and Press, Ofir},
  journal={arXiv preprint arXiv:2405.15793},
  year={2024},
  url={https://arxiv.org/abs/2405.15793}
}
```

```bibtex
@article{sellier2024browsergym,
  title={The BrowserGym Ecosystem for Web Agent Research},
  author={Le Sellier De Chezelles, Thibault and Gasse, Maxime and Drouin, Alexandre and Caccia, Massimo and Boisvert, Léo and Thakkar, Megh and Marty, Tom and Assouel, Rim and Shayegan, Sahar Omidi and Jang, Lawrence Keunho and others},
  journal={arXiv preprint arXiv:2412.05467},
  year={2024},
  url={https://arxiv.org/abs/2412.05467}
}
```

```bibtex
@article{xie2024osworld,
  title={OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments},
  author={Xie, Tianbao and Zhang, Danyang and Chen, Jixuan and Li, Xiaochuan and Zhao, Siheng and Cao, Ruisheng and Hua, Toh Jing and Cheng, Zhoujun and Shin, Dongchan and Lei, Fangyu and others},
  journal={arXiv preprint arXiv:2404.07972},
  year={2024},
  url={https://arxiv.org/abs/2404.07972}
}
```

```bibtex
@inproceedings{yao2023react,
  title={ReAct: Synergizing Reasoning and Acting in Language Models},
  author={Yao, Shunyu and Zhao, Jeffrey and Yu, Dian and Du, Nan and Shafran, Izhak and Narasimhan, Karthik and Cao, Yuan},
  booktitle={International Conference on Learning Representations},
  year={2023},
  url={https://openreview.net/forum?id=WwGWMAktQY}
}
```

---

# 50. Final Architecture Summary

The most useful mental model is:

```text
                         ┌──────────────────┐
                         │      USER        │
                         └────────┬─────────┘
                                  ↓
                         ┌──────────────────┐
                         │   SUPERVISOR     │
                         │  Task Routing    │
                         └────────┬─────────┘
                                  ↓
                   ┌──────────────┴──────────────┐
                   ↓                             ↓
          Workflow Retrieval              Tool Retrieval
                   ↓                             ↓
                   └──────────────┬──────────────┘
                                  ↓
                       Specialized Agent
                                  ↓
              ┌───────────────────┼───────────────────┐
              ↓                   ↓                   ↓
         Code Agent         Browser Agent         OS Agent
              ↓                   ↓                   ↓
          Code Tools          Web Tools           OS Tools
              └───────────────────┼───────────────────┘
                                  ↓
                           Testing Agent
                                  ↓
                             Validation
                                  ↓
                          Workflow Update
                                  ↓
                         Semantic Memory
                                  ↓
                            Next Context
                                  ↓
                               LLM
```

The central distinction for the thesis is:

```text
Agent
  =
Reasoning + State + Tool Selection + Execution Control

Tool
  =
Specific executable capability

Environment
  =
Repository / Browser / Desktop / Test Runtime

Memory
  =
Persisted information

Workflow
  =
Structured representation of the task and its execution state

Retrieval
  =
Mechanism for selecting relevant memory/tools/workflows
```

This gives Ecogent a clear research position: the specialized-agent pattern provides the **execution architecture**, while your proposed contribution focuses on **workflow representation, semantic retrieval, selective tool/context exposure, and cost-aware orchestration**.
