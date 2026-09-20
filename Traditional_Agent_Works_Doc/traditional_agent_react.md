# Traditional Agent: ReAct (Reasoning + Acting)

## 1. Overview

**ReAct** stands for **Reasoning + Acting**. It is a foundational paradigm for LLM-based agents in which the model interleaves reasoning with actions and observations:

```text
Reason → Act → Observe → Reason → Act → Observe → ...
```

The primary reference is:

**Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023).**  
*ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR 2023.

- arXiv: https://arxiv.org/abs/2210.03629
- OpenReview: https://openreview.net/forum?id=WwGWMAktQY
- Project: https://react-lm.github.io/

The paper describes interleaving reasoning traces and task-specific actions. Reasoning helps the model track/update plans and handle exceptions, while actions allow interaction with external sources and environments.

---

# 2. Why ReAct Was Proposed

Earlier LLM approaches often separated reasoning and acting.

### Reasoning-only

```text
Question
   ↓
LLM
   ↓
Reasoning
   ↓
Answer
```

The model may reason from incomplete or outdated internal knowledge.

### Acting-only

```text
User
 ↓
Agent
 ↓
Action
 ↓
Observation
 ↓
Action
```

Without an effective reasoning process, deciding what to do next can be difficult.

### ReAct

```text
Question
   ↓
Reason
   ↓
Action
   ↓
Observation
   ↓
Reason
   ↓
Action
   ↓
Observation
   ↓
Answer
```

The key idea is the feedback loop between the model and its environment.

---

# 3. Core ReAct Loop

```text
                ┌──────────────┐
                │     User     │
                └──────┬───────┘
                       ↓
                ┌──────────────┐
                │     LLM      │
                │   Reason     │
                └──────┬───────┘
                       ↓
                 Select Action
                       ↓
                ┌──────────────┐
                │ Environment  │
                │ / Tool / API │
                └──────┬───────┘
                       ↓
                  Observation
                       ↓
                ┌──────────────┐
                │     LLM      │
                │    Reason    │
                └──────┬───────┘
                       ↓
                    Action
                       ↓
                      ...
```

The important property is the **iterative feedback loop**.

---

# 4. ReAct Trajectory

A trajectory can be represented as:

```text
Thought₁
Action₁
Observation₁
Thought₂
Action₂
Observation₂
...
Thoughtₙ
Actionₙ
Observationₙ
Final Answer
```

Example:

```text
Thought:
I need information about the company.

Action:
Search("company revenue 2025")

Observation:
Several sources were found.

Thought:
I should inspect the official annual report.

Action:
Open("annual_report.pdf")

Observation:
The report contains the revenue figure.

Thought:
I now have sufficient evidence.

Final Answer:
The reported revenue was ...
```

The next reasoning step depends on the previous observation.

---

# 5. ReAct vs Chain-of-Thought

### Chain-of-thought style

```text
Question
   ↓
Reason
   ↓
Reason
   ↓
Reason
   ↓
Answer
```

### ReAct

```text
Question
   ↓
Reason
   ↓
Action
   ↓
Observation
   ↓
Reason
   ↓
Action
   ↓
Observation
   ↓
Answer
```

The key difference is that ReAct introduces interaction with an external environment.

---

# 6. What Is an Action?

An action is an operation the agent performs against an external environment.

Examples:

```text
Search the web
Read a file
Query a database
Call an API
Open a webpage
Execute code
Run tests
Navigate an environment
```

In a modern structured tool-calling implementation, an action may look conceptually like:

```json
{
  "name": "search_web",
  "arguments": {
    "query": "Django authentication best practices"
  }
}
```

The exact representation depends on the model/API.

---

# 7. What Is an Observation?

An observation is the result returned after an action.

Example:

```text
Action:
search_web("Django authentication")

Observation:
Search returned 10 results.
```

Or:

```text
Action:
read_file("settings.py")

Observation:
AUTH_USER_MODEL = "userapp.AppUser"
```

The observation becomes information for the next reasoning step.

---

# 8. ReAct Is Not the Same as a Tool

These concepts should be kept separate:

### LLM
Generates the next reasoning/action decision.

### Tool
Provides an executable capability.

### Agent Runtime
Executes actions, validates them, manages state, and returns results.

### ReAct
Describes the **reasoning + acting interaction pattern**.

Therefore:

```text
ReAct ≠ Tool
ReAct ≠ LLM
ReAct ≠ Agent Runtime
```

A useful abstraction is:

```text
                ReAct Pattern
                     │
          ┌──────────┴──────────┐
          ↓                     ↓
       Reason                  Act
          │                     │
          └──────────┬──────────┘
                     ↓
                Observation
                     ↓
                   Reason
```

---

# 9. ReAct With a Tool Runtime

A modern implementation can be represented as:

```text
User
 ↓
Agent Runtime
 ↓
Context Builder
 ↓
LLM
 ↓
Reasoning / Decision
 ↓
Tool Call
 ↓
Tool Runtime
 ↓
Tool Execution
 ↓
Tool Result
 ↓
Context / State Update
 ↓
LLM
 ↓
Reasoning / Decision
 ↓
...
 ↓
Final Answer
```

The LLM normally does not directly execute the Python function, shell command, HTTP request, or filesystem operation.

Instead:

```text
LLM
 ↓
Structured Tool Call
 ↓
Runtime
 ↓
Actual Tool
 ↓
Tool Result
 ↓
LLM
```

---

# 10. Coding-Agent Example

User:

```text
Fix the login bug in my Django project.
```

A ReAct-style trajectory could be:

```text
Thought:
I need to inspect the authentication implementation.

Action:
search_code("login authentication")

Observation:
login() is in userapp/views.py.

Thought:
I need to inspect the file.

Action:
read_file("userapp/views.py")

Observation:
The login view uses email authentication.

Thought:
I should inspect the authentication configuration.

Action:
read_file("settings.py")

Observation:
The custom email backend is not registered.

Thought:
I should inspect the backend implementation.

Action:
read_file("userapp/backends.py")

Observation:
EmailBackend exists and authenticates by email.

Thought:
The backend exists but is not registered in settings.

Action:
edit_file("settings.py", ...)

Observation:
File updated successfully.

Thought:
I should verify the fix.

Action:
run_tests("authentication")

Observation:
All authentication tests passed.

Final:
The login issue was caused by the custom email authentication
backend not being registered. I enabled it and verified the tests.
```

This demonstrates:

```text
Reason → Action → Observation
        ↓
Reason → Action → Observation
        ↓
Reason → Action → Observation
```

---

# 11. ReAct Handles Exceptions

One important property is adaptation.

Example:

```text
Reason:
I should read config.py.

Action:
read_file("config.py")

Observation:
File does not exist.

Reason:
The project may use settings.py.

Action:
list_directory()

Observation:
settings.py exists.

Reason:
I should inspect settings.py.

Action:
read_file("settings.py")
```

The model changes its next action based on the observation.

This is different from a completely predetermined workflow.

---

# 12. ReAct and Planning

ReAct does not require the model to generate the entire plan before execution.

Planning can be incremental:

```text
Current Goal
     ↓
Reason about next step
     ↓
Act
     ↓
Observe
     ↓
Update understanding
     ↓
Reason about next step
```

This is often described as **interleaved planning and execution**.

The plan can change after new information becomes available.

---

# 13. ReAct and Working Context

The next model call needs enough information to understand the previous trajectory.

Conceptually:

```text
System Instructions
        +
User Request
        +
Previous Actions
        +
Previous Observations
        +
Available Tools
        ↓
       LLM
```

As the trajectory grows, the context can grow too.

---

# 14. ReAct Context Growth

Suppose an agent performs 20 actions.

The context may contain:

```text
User request
System instructions
Tool definitions
Action 1
Observation 1
Action 2
Observation 2
...
Action 20
Observation 20
```

Conceptually:

```text
Context Size
   ↑
   │                         /
   │                       /
   │                    /
   │                 /
   │              /
   │___________/________________→ Number of steps
```

Longer trajectories can increase:

- input tokens
- latency
- model cost
- context-window pressure

This is particularly relevant to cost-aware agent research.

---

# 15. ReAct and Tool Results

Tool results normally become part of the current trajectory/context.

For example:

```text
Action:
read_file("models.py")

Observation:
class User(models.Model):
    ...
```

The next model call can use that observation.

However, a tool result does **not automatically become permanent long-term memory**.

Distinguish:

```text
Tool Result
   ↓
Current Context / Working State
```

from:

```text
Tool Result
   ↓
Memory Extraction
   ↓
Persistent Memory
```

The second path requires an explicit memory mechanism.

---

# 16. ReAct and Memory

A basic ReAct agent can work without a vector database.

For example:

```python
trajectory = [
    user_message,
    thought,
    action,
    observation,
    thought,
    action,
    observation
]
```

More advanced agents may combine ReAct-style execution with:

- conversation history
- summaries
- checkpoints
- persistent memory
- databases
- vector retrieval
- project files
- workflow state

Therefore:

> **ReAct is an interaction pattern, not a specific memory architecture.**

---

# 17. ReAct and Vector Databases

ReAct itself does not require:

- FAISS
- Chroma
- Pinecone
- Weaviate
- another vector database

A simple system can be:

```text
LLM
 ↓
ReAct Loop
 ↓
Tools
```

A more advanced system could be:

```text
LLM
 ↓
ReAct Loop
 ↓
Memory Retrieval
 ↓
Tools
```

Or:

```text
LLM
 ↓
ReAct Loop
 ↓
Workflow Retrieval
 ↓
Tool Retrieval
 ↓
Tools
```

The vector database is an optional retrieval component.

---

# 18. ReAct and Modern Tool Calling

The original ReAct work used action/observation interactions with external environments.

Modern LLM APIs commonly expose structured tool calling.

A contemporary ReAct-like loop can therefore be:

```text
LLM
 │
 │ tool call
 ↓
Runtime
 │
 │ execute
 ↓
Tool
 │
 │ result
 ↓
Runtime
 │
 │ tool result
 ↓
LLM
```

The underlying principle remains:

```text
Reason → Act → Observe → Reason
```

The action representation may simply be a structured function/tool call.

---

# 19. ReAct vs Fixed Workflow

### Fixed workflow

```text
Step 1
 ↓
Step 2
 ↓
Step 3
 ↓
Step 4
```

The execution path is predetermined.

### ReAct

```text
Reason
 ↓
Action
 ↓
Observation
 ↓
Reason
 ↓
Choose next action
 ↓
Observation
 ↓
...
```

The next action depends on the current observation.

This makes the agent adaptive, but potentially less predictable and potentially more expensive because more model calls may be required.

---

# 20. ReAct vs Ecogent

A useful conceptual comparison for your thesis is:

### Traditional ReAct-style agent

```text
User
 ↓
LLM
 ↓
Action
 ↓
Tool
 ↓
Observation
 ↓
LLM
 ↓
Action
 ↓
Tool
 ↓
Observation
```

### Proposed Ecogent-style architecture

```text
User
 ↓
Tiny Local Supervisor
 ↓
Task / Intent Routing
 ↓
Workflow Retrieval
 ↓
Relevant Tool Retrieval
 ↓
Specialized Agent
 ↓
LLM
 ↓
Tool
 ↓
Observation
 ↓
Workflow State Update
 ↓
Semantic Workflow Memory
 ↓
Next Context
 ↓
LLM
```

The research opportunity is not to claim that ReAct is replaced.

Instead, Ecogent can investigate whether **structured workflow memory and semantic retrieval can reduce unnecessary context and tool-selection overhead around iterative agent execution**.

---

# 21. Potential Cost Problem

A simplified ReAct agent may repeatedly send:

```text
System Prompt
+
User Request
+
Tool Definitions
+
Previous Trajectory
+
New Observation
```

to the LLM.

For example:

```text
Step 1 → 1,000 input tokens
Step 2 → 1,500 input tokens
Step 3 → 2,000 input tokens
Step 4 → 2,500 input tokens
Step 5 → 3,000 input tokens
```

The total input-token consumption can grow substantially.

A cost-aware architecture could instead construct:

```text
Current Goal
+
Relevant Workflow State
+
Relevant Retrieved Memory
+
Relevant Tool Schemas
+
Latest Observation
```

rather than always providing the complete historical trajectory.

This is a **research hypothesis**, not a guaranteed improvement.

---

# 22. ReAct + Structured Workflow Memory

A possible extension is:

```text
                 User
                   ↓
                LLM/Agent
                   ↓
                 Reason
                   ↓
                  Act
                   ↓
                 Tool
                   ↓
              Observation
                   ↓
           Workflow Manager
                   ↓
        ┌──────────┴──────────┐
        ↓                     ↓
 Current State          Persistent Memory
        ↓                     ↓
   Next Context          Semantic Index
        └──────────┬──────────┘
                   ↓
                  LLM
```

Instead of preserving every historical observation in the active prompt, the system can preserve structured state and retrieve only relevant historical information.

This directly connects ReAct to the Ecogent research problem.

---

# 23. Important Research Distinction

Avoid writing:

> “Traditional agents use ReAct.”

That is too broad.

Prefer:

> “ReAct is a foundational reasoning-and-acting paradigm for LLM agents. Modern agent systems may implement related iterative reasoning/action loops using structured tool calling, workflow state, memory, planning, or other orchestration mechanisms.”

Also avoid:

> “Claude Code uses ReAct.”

Unless the implementation is explicitly documented, proprietary internals should not be assumed to exactly follow the ReAct architecture.

A safer statement is:

> “Coding agents exhibit behaviors that can be analyzed using reasoning-action-observation concepts, but proprietary internal implementations should not be assumed to exactly follow ReAct.”

---

# 24. Advantages of ReAct

ReAct provides several important capabilities.

### 1. External information access

The agent can obtain information from tools or environments.

### 2. Adaptive execution

The next action can depend on the latest observation.

### 3. Exception handling

Unexpected observations can change the next action.

### 4. Interleaved reasoning and action

Planning can happen together with execution.

### 5. Inspectable trajectories

Reasoning/action/observation trajectories provide a useful object for studying agent behavior.

The original paper evaluated ReAct on question answering, fact verification, and interactive decision-making benchmarks including ALFWorld and WebShop.

---

# 25. Limitations of ReAct

### 1. Context growth

Long trajectories can increase context size.

### 2. More LLM calls

Every reasoning/action cycle may require another model invocation.

### 3. Tool-selection errors

The model may choose an inappropriate tool.

### 4. Incorrect actions

A bad action can produce an unhelpful observation.

### 5. Loops

The agent can repeat similar actions:

```text
Search
 ↓
Observation
 ↓
Search
 ↓
Observation
 ↓
Search
 ↓
...
```

### 6. Cost

More model calls and larger prompts can increase inference cost.

### 7. Latency

Sequential execution can make tasks slower.

These limitations motivate research into workflow management, retrieval, context compression, and cost-aware execution.

---

# 26. ReAct Pseudocode

A simplified implementation:

```python
def react_agent(user_input):
    trajectory = [user_input]

    while True:
        response = llm(
            context=trajectory,
            tools=available_tools
        )

        if response.type == "final":
            return response.content

        action = response.tool_call

        result = execute_tool(
            action.name,
            action.arguments
        )

        trajectory.append(action)
        trajectory.append(result)
```

The core loop is:

```text
LLM
 ↓
Action
 ↓
Tool
 ↓
Observation
 ↓
LLM
```

A production implementation also needs validation, permissions, error handling, timeouts, logging, and state management.

---

# 27. ReAct With Tool Validation

A safer implementation adds a runtime boundary:

```text
LLM
 ↓
Tool Call
 ↓
Validate Tool Name
 ↓
Validate Arguments
 ↓
Check Permissions
 ↓
Execute
 ↓
Tool Result
 ↓
LLM
```

This reinforces:

```text
LLM decides
Runtime controls
Tool executes
```

The LLM should not itself be treated as the security boundary.

---

# 28. ReAct Trajectory as Agent State

A useful abstraction is:

```text
State_t
   ↓
LLM
   ↓
Action_t
   ↓
Environment
   ↓
Observation_t
   ↓
State_(t+1)
   ↓
LLM
```

Conceptually:

```text
State_(t+1) =
Update(State_t, Action_t, Observation_t)
```

This abstraction is useful when connecting ReAct to graph-based agent frameworks and workflow systems.

---

# 29. Relation to LangGraph

LangGraph can represent an iterative agent loop using graph state.

Conceptually:

```text
START
  ↓
Agent / LLM
  ↓
Tool?
 ┌───────┴───────┐
 │               │
Yes              No
 │               │
 ↓               ↓
Tools           END
 │
 ↓
Update State
 │
 └──────→ Agent / LLM
```

However:

> **LangGraph is an orchestration/state framework; ReAct is a reasoning-and-acting paradigm.**

They operate at different abstraction levels.

---

# 30. Research Relevance to Ecogent

ReAct can serve as an important conceptual baseline for your thesis.

A useful comparison is:

| Dimension | Basic ReAct Agent | Proposed Ecogent |
|---|---|---|
| Reasoning | LLM | LLM + supervisor |
| Acting | Tool calls | Specialized agents + tools |
| State | Trajectory/runtime state | Structured workflow state |
| Memory | Optional | Explicit workflow memory |
| Retrieval | Optional | Semantic workflow/tool retrieval |
| Tool selection | LLM/tool schema | Retrieved relevant tools + agent |
| Context | Often trajectory-based | Selective context construction |
| Orchestration | Agent loop | LangGraph/workflow manager |
| Cost optimization | Not the central mechanism | Explicit research objective |
| Workflow reuse | Optional | Core design goal |

This is an architectural comparison, not a claim that every ReAct implementation has exactly these properties.

---

# 31. Recommended Thesis Positioning

A strong literature-review paragraph is:

> ReAct established a general paradigm in which language models interleave reasoning with environment interaction. This enables agents to acquire external information and adapt their actions according to intermediate observations. However, iterative reasoning and acting can produce long trajectories and repeated context transmission. The proposed Ecogent architecture investigates whether structured workflow representations and semantic retrieval can preserve relevant task state while reducing unnecessary context supplied to the reasoning model.

---

# 32. Primary Reference

**Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023).**

*ReAct: Synergizing Reasoning and Acting in Language Models.*

International Conference on Learning Representations (ICLR 2023).

- arXiv: https://arxiv.org/abs/2210.03629
- OpenReview: https://openreview.net/forum?id=WwGWMAktQY
- PDF: https://arxiv.org/pdf/2210.03629
- Project: https://react-lm.github.io/

---

# 33. Related References

## Chain-of-Thought

Wei, J., et al. (2022).  
*Chain-of-Thought Prompting Elicits Reasoning in Large Language Models.*

NeurIPS 2022.

https://arxiv.org/abs/2201.11903

---

## Toolformer

Schick, T., et al. (2023).  
*Toolformer: Language Models Can Teach Themselves to Use Tools.*

NeurIPS 2023.

https://arxiv.org/abs/2302.04761

---

## MRKL Systems

Karpas, E., et al. (2022).  
*MRKL Systems: A Modular, Neuro-Symbolic Architecture That Combines Large Language Models, External Knowledge Sources and Discrete Reasoning.*

https://arxiv.org/abs/2205.00445

---

## ReSpAct

Dongre, V., Yang, X., Acikgoz, E. C., Dey, S., Tur, G., & Hakkani-Tür, D. (2024).  
*ReSpAct: Harmonizing Reasoning, Speaking, and Acting Towards Building Large Language Model-Based Conversational AI Agents.*

https://arxiv.org/abs/2411.00927

ReSpAct extends the reasoning/action idea with explicit conversational interaction and clarification.

---

# 34. Citation-Ready BibTeX

```bibtex
@inproceedings{yao2023react,
  title={ReAct: Synergizing Reasoning and Acting in Language Models},
  author={Yao, Shunyu and Zhao, Jeffrey and Yu, Dian and Du, Nan and Shafran, Izhak and Narasimhan, Karthik and Cao, Yuan},
  booktitle={International Conference on Learning Representations},
  year={2023},
  url={https://openreview.net/forum?id=WwGWMAktQY}
}
```

```bibtex
@article{yao2022react,
  title={ReAct: Synergizing Reasoning and Acting in Language Models},
  author={Yao, Shunyu and Zhao, Jeffrey and Yu, Dian and Du, Nan and Shafran, Izhak and Narasimhan, Karthik and Cao, Yuan},
  journal={arXiv preprint arXiv:2210.03629},
  year={2022},
  url={https://arxiv.org/abs/2210.03629}
}
```

---

# 35. Final Summary

The fundamental ReAct loop is:

```text
┌───────────────┐
│     User      │
└───────┬───────┘
        ↓
┌───────────────┐
│     Reason    │
│      LLM      │
└───────┬───────┘
        ↓
┌───────────────┐
│     Action    │
└───────┬───────┘
        ↓
┌───────────────┐
│ Tool / Env.   │
└───────┬───────┘
        ↓
┌───────────────┐
│  Observation  │
└───────┬───────┘
        ↓
┌───────────────┐
│     Reason    │
│      LLM      │
└───────┬───────┘
        ↓
      Action
        ↓
      ...
```

In one sentence:

> **ReAct is an agent paradigm where an LLM repeatedly reasons about a task, takes an action in an external environment, observes the result, and uses that observation to determine its next reasoning/action step.**

For Ecogent, the important connection is:

```text
ReAct
  ↓
Iterative Reason → Act → Observe
  ↓
Longer trajectories
  ↓
More context / repeated model calls
  ↓
Potential cost + latency
  ↓
Ecogent research question
  ↓
Can structured workflow memory +
semantic retrieval reduce unnecessary context
while maintaining task success?
```
