# Traditional Agent Memory and Context Management

## 1. Purpose

This document explains how a traditional tool-using AI agent manages memory and builds the context sent to an LLM on each model call.

The focus is **memory and context management only**. It does not assume a particular vendor or framework.

The central idea is:

> An agent does not normally give the LLM one permanent memory object. The agent runtime stores different kinds of state and constructs a context for each LLM call from the information that is relevant at that moment.

---

# 2. High-Level Architecture

```text
                         USER
                           |
                           v
                  +------------------+
                  |  Agent Runtime   |
                  +--------+---------+
                           |
            +--------------+---------------+
            |              |               |
            v              v               v
      System / Agent   Conversation    Project / Task
       Instructions       History          State
            |              |               |
            +--------------+---------------+
                           |
                           v
                  +------------------+
                  | Context Builder  |
                  +--------+---------+
                           |
             +-------------+-------------+
             |                           |
             v                           v
       Relevant Memory             Tool Definitions
             |                           |
             +-------------+-------------+
                           |
                           v
                         LLM
                           |
                    +------+------+
                    |             |
                    v             v
                 Answer       Tool Call
                                  |
                                  v
                               Tool
                                  |
                                  v
                            Tool Result
                                  |
                                  v
                         Update Runtime State
                                  |
                                  v
                         Build Next Context
                                  |
                                  v
                                 LLM
```

The important loop is:

```text
Context -> LLM -> Action/Tool -> Result -> State Update -> New Context -> LLM
```

---

# 3. What Is "Memory" in a Traditional Agent?

The word **memory** can mean several different things.

A useful classification is:

```text
Agent Memory
|
+-- 1. Conversation / Episodic History
|
+-- 2. Working Memory / Runtime State
|
+-- 3. Project or Environment State
|
+-- 4. Summaries / Compacted History
|
+-- 5. Persistent Long-Term Memory
|
+-- 6. Retrieved Memory
|
+-- 7. Tool / Execution History
```

These do not necessarily use the same storage format.

---

# 4. Conversation / Episodic Memory

## What it is

Conversation memory contains previous interaction items.

For example:

```text
User:
Create a login system.

Assistant:
I will inspect the project.

Assistant -> Tool:
read_file("settings.py")

Tool:
[file contents]

Assistant:
The project uses Django authentication.
```

A simplified internal representation could look like:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Create a login system."
    },
    {
      "role": "assistant",
      "content": "I will inspect the project."
    },
    {
      "role": "tool_call",
      "name": "read_file",
      "arguments": {
        "path": "settings.py"
      }
    },
    {
      "role": "tool_result",
      "name": "read_file",
      "content": "..."
    },
    {
      "role": "assistant",
      "content": "The project uses Django authentication."
    }
  ]
}
```

The exact schema differs between frameworks and model APIs.

## Why it exists

Conversation history gives the LLM continuity:

```text
Turn 1
    |
    v
Turn 2
    |
    v
Turn 3
    |
    v
Turn 4
```

Without some form of history, the model would not know what was previously discussed.

## Important limitation

Conversation history is not necessarily sent forever in its original form.

As it grows, it can be:

- truncated
- summarized
- compacted
- selectively retrieved
- replaced partly by structured state

---

# 5. Working Memory / Runtime State

Working memory is information needed to complete the **current task**.

It is different from the entire conversation.

Example:

```json
{
  "task": "Fix OTP login",
  "current_step": "Inspect OTP verification",
  "files_inspected": [
    "users/views.py",
    "users/otp.py"
  ],
  "test_status": "failing",
  "current_error": "Invalid OTP"
}
```

This state may exist only during the current run.

A workflow/agent framework may keep it as an internal state object.

Conceptually:

```text
Current task
    |
    +-- current step
    +-- completed steps
    +-- pending steps
    +-- tool results
    +-- errors
    +-- intermediate decisions
```

Working memory is often more useful to an agent than replaying a huge conversation.

---

# 6. Project / Environment State

For coding agents, the project itself is an extremely important form of persistent state.

For example:

```text
project/
|
+-- README.md
+-- source/
+-- tests/
+-- config/
+-- package.json
+-- requirements.txt
```

The agent can inspect these files when needed.

This means:

> The project filesystem is often part of the agent's external memory.

For example, the agent may remember from the conversation:

```text
"Authentication was implemented."
```

But the current source code is the authoritative state for what actually exists now.

The agent can therefore:

```text
Previous conversation
        |
        v
Background information
        |
        v
Current project state
        |
        v
Verify actual implementation
```

This is especially important because another person or process may have changed the files after the previous conversation.

---

# 7. System / Agent Instructions

A traditional agent also has predefined instructions.

For example:

```text
You are a coding agent.

Rules:
1. Inspect files before editing.
2. Use available tools when necessary.
3. Do not invent file contents.
4. Run relevant tests after modifications.
5. Explain completed changes.
```

These instructions are usually configured before the conversation.

They are not normally "remembered" from the conversation.

They are part of the agent configuration.

Conceptually:

```text
Agent configuration
        |
        v
System / developer instructions
        |
        v
Every relevant model call
```

---

# 8. Tool Definitions Are Also Context

The LLM needs to know which actions it is allowed to request.

For example:

```json
{
  "name": "read_file",
  "description": "Read the contents of a file.",
  "parameters": {
    "path": "string"
  }
}
```

Another:

```json
{
  "name": "edit_file",
  "description": "Modify an existing file.",
  "parameters": {
    "path": "string",
    "content": "string"
  }
}
```

The LLM generally receives the **tool schema/description**, not the implementation.

The runtime owns the actual implementation:

```text
LLM
 |
 | "call read_file"
 v
Agent Runtime
 |
 v
Python/function/tool implementation
 |
 v
File system
```

---

# 9. Tool Execution History

Tool calls and results become part of the current execution context.

Example:

```text
User:
Fix the authentication bug.

Assistant:
I need to inspect the authentication code.

Tool Call:
search_code("authentication")

Tool Result:
users/views.py
users/models.py
users/tests.py

Tool Call:
read_file("users/views.py")

Tool Result:
[file contents]
```

The next LLM call can receive the relevant previous tool calls/results.

This creates the agent's short-term execution memory:

```text
User request
    |
Tool call
    |
Tool result
    |
Tool call
    |
Tool result
    |
LLM
```

Not every tool result needs to become permanent memory.

---

# 10. Long-Term Persistent Memory

Long-term memory contains information that may be useful across future tasks or sessions.

Examples:

```text
Project uses PostgreSQL.

User prefers pytest.

Authentication uses JWT.

Deployment uses Docker.

Previous task established API endpoint /api/login/.
```

Persistent memory can be stored in many ways:

```text
Files
Database
Key-value store
Document store
Vector index
Search index
Structured state store
```

There is no requirement that long-term memory must use a vector database.

A system may use plain files.

Example:

```text
memory/
|
+-- project_preferences.md
+-- known_issues.md
+-- architecture.md
```

Or structured storage:

```json
{
  "memory_id": "M001",
  "topic": "database",
  "content": "Project uses PostgreSQL",
  "scope": "project"
}
```

---

# 11. Memory Is Often Scoped

A useful memory system distinguishes scope.

```text
Memory
|
+-- User-level
|     |
|     +-- user preferences
|
+-- Project-level
|     |
|     +-- architecture
|     +-- conventions
|
+-- Session-level
|     |
|     +-- current conversation
|
+-- Task-level
      |
      +-- current execution state
```

This prevents unrelated information from being inserted into every model call.

For example:

```text
Project A:
PostgreSQL

Project B:
MongoDB
```

The agent should not blindly mix them.

---

# 12. How Memory Is Built

Memory can come from several sources.

## A. User input

User says:

> "This project always uses pytest."

The system may store this as persistent project information.

---

## B. Tool observations

The agent discovers:

```text
requirements.txt:
pytest
```

The system may infer:

```text
Project testing framework = pytest
```

However, discovering something during a task does not automatically mean it should become permanent memory.

A memory policy may decide whether it is useful enough.

---

## C. Completed workflow/task

After a task:

```text
Task:
Implement OTP login.

Result:
Completed successfully.
```

A system may produce a summary:

```text
OTP login implemented using email verification.
```

That summary can become persistent memory.

---

## D. Explicit memory instructions

Some systems allow the user to explicitly request persistence:

```text
"Remember that this project uses PostgreSQL."
```

The system can store that as long-term memory.

---

# 13. Memory Creation Is Usually Selective

A good memory system should not save every event.

For example:

```text
Tool:
ls

Result:
10 files
```

This usually has little long-term value.

But:

```text
The project uses PostgreSQL 16.
```

may have long-term value.

Therefore a memory system can use a decision step:

```text
New information
      |
      v
Is it useful later?
      |
   +--+--+
   |     |
  No    Yes
   |     |
Discard  Store
```

This is an important distinction:

> **Execution history is not the same thing as long-term memory.**

---

# 14. Memory Retrieval

When a new request arrives, the agent does not necessarily load every stored memory.

Instead, it can retrieve relevant information.

There are several approaches.

## 14.1 Direct lookup

Example:

```text
project_id = P001
```

Load:

```text
P001 project settings
```

This is useful for structured information.

---

## 14.2 Keyword/search retrieval

Query:

```text
"PostgreSQL"
```

Search stored memory.

---

## 14.3 Semantic retrieval

The query:

```text
"The database connection is failing"
```

could retrieve memory:

```text
"Project uses PostgreSQL with Docker."
```

A vector index can be used for this.

The important architecture is:

```text
Query
  |
  v
Embedding
  |
  v
Vector search
  |
  v
Memory IDs
  |
  v
Metadata/database
  |
  v
Actual memory
```

The vector index is therefore a **retrieval mechanism**, not necessarily the authoritative memory store.

---

# 15. Context Building

This is one of the most important parts of an agent.

The agent has many possible sources:

```text
System instructions
Conversation history
Current user request
Current task state
Project state
Retrieved memories
Tool definitions
Previous tool results
```

But it cannot necessarily send everything.

So a context-building stage determines what should be included.

Conceptually:

```text
                   Context Sources
                        |
       +----------------+----------------+
       |                |                |
       v                v                v
  Instructions      Conversation      Memory
       |                |                |
       +----------------+----------------+
                        |
                        v
                 Current Task State
                        |
                        v
                 Context Selection
                        |
                        v
                 Context Construction
                        |
                        v
                       LLM
```

---

# 16. Example Context Build — New Chat / New Project

User starts a new project and says:

> "Add Google authentication."

There is no previous conversation.

The runtime may build:

```text
SYSTEM:
You are a coding agent...

USER:
Add Google authentication.

PROJECT:
Current workspace information.

TOOLS:
read_file
search_code
edit_file
run_command
run_tests
```

Then the LLM may call:

```text
search_code("authentication")
```

The tool returns:

```text
users/models.py
users/views.py
settings.py
```

The next context becomes:

```text
SYSTEM
+
USER
+
Previous tool call
+
Tool result
+
TOOLS
```

Then the LLM continues.

---

# 17. Example Context Build — Existing Chat / Existing Project

Suppose the previous task was:

```text
Implement OTP authentication.
```

Today the user says:

> "OTP is still failing."

The agent may have:

```text
SYSTEM
+
Relevant conversation history
+
Current user request
+
Current project state
+
Relevant persistent memory
+
Available tools
```

The agent can then inspect the current files rather than blindly trusting old conversation information.

For example:

```text
Previous memory:
"OTP authentication was implemented."

Current project:
users/otp.py exists.

Current task:
OTP verification is failing.
```

Then it calls:

```text
read_file("users/otp.py")
```

and continues.

---

# 18. Context Is Rebuilt for Each Model Call

This is critical.

Suppose:

```text
LLM CALL #1
```

Context:

```text
System
+
User
+
Tools
```

The LLM requests:

```text
read_file("otp.py")
```

After execution:

```text
LLM CALL #2
```

Context may now contain:

```text
System
+
User
+
Previous assistant/tool call
+
Tool result
+
Tools
```

Then the model requests:

```text
edit_file(...)
```

Next:

```text
LLM CALL #3
```

Context contains the necessary state/results from the preceding steps.

Therefore:

> **The LLM is repeatedly called with a newly constructed context.**

The agent runtime is responsible for maintaining continuity.

---

# 19. Context Flowchart

```text
                         USER MESSAGE
                              |
                              v
                    +--------------------+
                    | Agent Runtime      |
                    +---------+----------+
                              |
       +----------------------+----------------------+
       |                      |                      |
       v                      v                      v
 System Instructions     Conversation History    Current State
       |                      |                      |
       |                      |                      |
       +----------------------+----------------------+
                              |
                              v
                    +--------------------+
                    | Memory Retrieval   |
                    +---------+----------+
                              |
                              v
                    Relevant Memory Only
                              |
                              v
                    +--------------------+
                    | Context Builder    |
                    +---------+----------+
                              |
              +---------------+---------------+
              |                               |
              v                               v
       Tool Definitions                 Context Messages
              |                               |
              +---------------+---------------+
                              |
                              v
                            LLM
                              |
                   +----------+----------+
                   |                     |
                   v                     v
                Answer               Tool Call
                                         |
                                         v
                                       Tool
                                         |
                                         v
                                   Tool Result
                                         |
                                         v
                               Runtime State Update
                                         |
                                         +----------+
                                                    |
                                                    v
                                             Context Builder
                                                    |
                                                    v
                                                   LLM
```

---

# 20. Context Compression

As conversation history grows, the agent may face a context-window problem.

Example:

```text
Turn 1       2,000 tokens
Turn 10     20,000 tokens
Turn 50     100,000 tokens
Turn 100    300,000 tokens
```

Sending all raw history repeatedly can become expensive or impossible.

Therefore systems can use:

```text
Truncation
Summarization
Compaction
Selective retrieval
Structured state
```

---

# 21. Truncation

The simplest strategy:

```text
Oldest messages
      |
      v
Remove
      |
      v
Keep recent messages
```

Example:

```text
Old:
Message 1
Message 2
Message 3
...
Message 50

Keep:
Message 40
Message 41
...
Message 50
```

Advantage:

- Simple
- Cheap

Problem:

- Important information from old messages can disappear.

---

# 22. Summarization

Instead of deleting old history:

```text
100 old messages
       |
       v
Summary
       |
       v
"User is building a Django application.
Authentication uses email login.
OTP was implemented.
Current problem is OTP expiration."
```

Then:

```text
Summary
+
Recent messages
```

can replace the original large history.

---

# 23. Compaction

Compaction is a broader concept.

Instead of only summarizing natural-language conversation, a system can create a smaller representation of the useful state.

For example:

```text
Original history:
50,000 tokens

Compacted state:
{
  "goal": "Fix OTP authentication",
  "completed": [
    "User model",
    "Email login"
  ],
  "current_issue": "OTP expiration",
  "files": [
    "users/otp.py",
    "users/views.py"
  ]
}
```

This can be much smaller than the original conversation.

---

# 24. Selective Retrieval

Another approach is:

```text
Huge historical memory
        |
        v
Current query
        |
        v
Retrieve only relevant information
```

Example:

```text
Current request:
"Why is OTP failing?"

Retrieved:
- OTP implementation summary
- Previous OTP-related error
- Relevant project file
```

Unrelated memories are excluded.

This is particularly useful for long-running agents.

---

# 25. Hybrid Context Management

A sophisticated agent can combine all of these.

```text
                  ALL AVAILABLE INFORMATION
                            |
        +-------------------+-------------------+
        |                   |                   |
        v                   v                   v
 Recent History       Structured State      Long-term Memory
        |                   |                   |
        +-------------------+-------------------+
                            |
                            v
                     Retrieval / Selection
                            |
                            v
                     Compression if needed
                            |
                            v
                      Context Builder
                            |
                            v
                            LLM
```

This is often more practical than relying on one memory mechanism.

---

# 26. Memory Update After a Task

A completed task can produce several outputs:

```text
Task execution
      |
      +-- Conversation history
      |
      +-- Tool execution history
      |
      +-- Updated project files
      |
      +-- Current workflow state
      |
      +-- Optional long-term memory
```

The important point is:

> Not all outputs become long-term memory.

A memory policy can decide:

```text
Was this information useful?
       |
   +---+---+
   |       |
  No      Yes
   |       |
Ignore    Store
```

---

# 27. Persistent Memory Update Flow

A conceptual memory-update pipeline:

```text
                    Task Execution
                          |
                          v
                   New Information
                          |
                          v
                 Memory Candidate
                          |
                          v
                 Relevance Check
                    /           \
                   /             \
                 No              Yes
                 |                |
                 v                v
              Discard       Normalize/Summarize
                                  |
                                  v
                             Add Metadata
                                  |
                                  v
                          Persistent Storage
                                  |
                                  v
                         Optional Search Index
```

Possible metadata:

```json
{
  "memory_id": "M001",
  "scope": "project",
  "topic": "authentication",
  "content": "Project uses email-based OTP authentication.",
  "source": "task_104",
  "created_at": "..."
}
```

---

# 28. Memory Does Not Have to Be Markdown

A traditional agent can use different storage mechanisms.

| Storage | Good for |
|---|---|
| Raw message history | Conversation continuity |
| JSON | Structured state |
| SQLite/PostgreSQL | Persistent structured memory |
| Markdown/text | Human-readable project instructions |
| Filesystem | Project/environment state |
| Search index | Keyword retrieval |
| Vector index | Semantic retrieval |
| Key-value store | Fast structured lookup |

A real system can combine several of these.

---

# 29. Memory vs Context

These two terms should not be confused.

### Memory

Information stored somewhere that **could potentially be used later**.

### Context

Information actually **given to the LLM for the current model call**.

For example:

```text
100 memories stored
       |
       v
Current request
       |
       v
Retrieve 5 relevant memories
       |
       v
Context Builder
       |
       v
LLM receives 5 memories
```

So:

```text
Memory ≠ Context
```

This distinction is extremely important.

---

# 30. Memory vs Project State

For coding agents:

```text
Memory:
"Authentication was implemented."

Project state:
users/views.py
users/models.py
settings.py
```

Memory gives background.

Project state gives the current actual implementation.

A good coding agent can use both.

---

# 31. Memory vs Tool History

Tool history:

```text
read_file("settings.py")
run_command("pytest")
search_code("OTP")
```

is primarily useful for the current execution.

Long-term memory:

```text
"Project uses PostgreSQL."
```

is useful across future tasks.

Therefore:

```text
Tool history
     |
     v
Short-term execution context

Useful learned information
     |
     v
Potential long-term memory
```

---

# 32. The Complete Traditional Memory Model

```text
                         AGENT MEMORY
                              |
        +---------------------+---------------------+
        |                     |                     |
        v                     v                     v
  Short-Term             Working State       Long-Term Memory
        |                     |                     |
        v                     v                     v
Conversation            Current Task        Persistent Facts
Tool Results            Current Step        Past Lessons
Recent Messages         Errors              Project Knowledge
        |                     |                     |
        +---------------------+---------------------+
                              |
                              v
                       Context Selection
                              |
                 +------------+------------+
                 |                         |
                 v                         v
            Compression              Retrieval
                 |                         |
                 +------------+------------+
                              |
                              v
                       Context Builder
                              |
                              v
                             LLM
                              |
                              v
                       Tool / Response
                              |
                              v
                       State / Memory
                         Update
```

---

# 33. Key Takeaways

### 1. An agent does not have one single memory.

It normally has several layers:

```text
Conversation
Working state
Project state
Long-term memory
Tool history
Summaries/compacted state
```

### 2. Memory is storage; context is what reaches the LLM.

```text
Memory
   ↓
Selection/Retrieval
   ↓
Context
   ↓
LLM
```

### 3. Tool calls become part of the current execution context.

```text
LLM
 ↓
Tool call
 ↓
Tool
 ↓
Result
 ↓
Context/state update
 ↓
LLM
```

### 4. Long-term memory is selective.

Not every message or tool result should become permanent memory.

### 5. Context is rebuilt repeatedly.

Each LLM call can receive a newly constructed context based on the latest state.

### 6. Large history can be managed through:

```text
Truncation
Summarization
Compaction
Retrieval
Structured state
```

### 7. Vector databases are optional.

A traditional agent can use:

```text
Files
Database
Search
Vector retrieval
or combinations
```

There is no universal requirement that agent memory must be stored in a vector database.

---

# 34. One-Sentence Mental Model

If you remember only one thing, remember this:

> **A traditional agent stores conversation/state/memory externally, selects and possibly compresses the relevant parts, builds a context for the LLM, lets the LLM request tools, feeds tool results back into the current context, updates state, and repeats until the task is complete.**

# 35. References and Official Documentation

## 35.1 Official Agent Framework and Company Documentation

### [1] OpenAI Agents SDK — Sessions
https://openai.github.io/openai-agents-python/sessions/

Relevant for conversation/session memory, retrieving history before a run, persisting new items after a run, and session storage such as SQLite, Redis, SQLAlchemy, MongoDB, and managed conversation storage.

### [2] OpenAI Agents SDK — Agent Memory
https://openai.github.io/openai-agents-python/sandbox/memory/

Relevant for long-term agent memory, memory extraction, consolidation, Markdown/file-based memory, summaries, and memory across runs.

### [3] OpenAI Agents SDK — Session Compaction
https://openai.github.io/openai-agents-python/ref/memory/session/

Relevant for context growth, conversation compaction, and continuing sessions after compaction.

### [4] OpenAI Agents SDK — Main Documentation
https://openai.github.io/openai-agents-python/

Relevant for agent runtime, tool execution, agent loops, sessions, handoffs, guardrails, and tracing.

### [5] Anthropic — Claude Code Project Configuration and Memory
https://code.claude.com/docs/fr/claude-directory

Relevant for `CLAUDE.md`, project instructions, filesystem-based context, persistent project memory, and auto-memory.

### [6] Anthropic — Claude Documentation
https://docs.anthropic.com/

Relevant for context windows, context management, compaction, long-running agent workflows, structured state, and progress information.

### [7] LangGraph — Checkpointing
https://langchain-ai.github.io/langgraph/reference/checkpoints/

Relevant for working memory, agent state, workflow state, checkpoints, persistence, and serialization.

### [8] LangChain — Deep Agents
https://docs.langchain.com/oss/javascript/deepagents/overview

Relevant for long-term memory, cross-thread memory, filesystem state, agent context, and subagents.

### [9] LangChain — Zep Integration
https://docs.langchain.com/oss/python/integrations/providers/zep/

Relevant for persistent conversation history, memory retrieval, summaries, semantic memory, and database-backed memory.

## 35.2 Primary Research Papers

### [10] ReAct
S. Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models," arXiv:2210.03629, 2022.

https://arxiv.org/abs/2210.03629

Relevant for reasoning/action/tool interaction and the reasoning → action → observation loop.

### [11] Generative Agents
J. S. Park et al., "Generative Agents: Interactive Simulacra of Human Behavior," Proceedings of the 36th Annual ACM Symposium on User Interface Software and Technology (UIST), 2023.

https://doi.org/10.1145/3586183.3606763

Relevant for experience memory, memory streams, reflection, retrieval, and using retrieved memories for planning and behavior.

### [12] MemGPT
C. Packer et al., "MemGPT: Towards LLMs as Operating Systems," arXiv, 2023.

https://research.memgpt.ai/

Relevant for hierarchical memory, context-window limitations, moving information between memory tiers, and virtual-memory-inspired context management.

### [13] Retrieval-Augmented Generation (RAG)
P. Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks," Advances in Neural Information Processing Systems (NeurIPS), 2020.

https://papers.nips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html

Relevant for external knowledge, dense vector retrieval, non-parametric memory, embeddings, and supplying retrieved information to an LLM.

Important distinction: RAG is a retrieval architecture and is not synonymous with agent memory, although it can be used as a memory mechanism inside an agent.

### [14] A-MEM
Y. Xu et al., "A-MEM: Agentic Memory for LLM Agents," arXiv:2502.12110, 2025.

https://arxiv.org/abs/2502.12110

Relevant for agentic memory, structured memory notes, memory organization, linking related memories, and updating memory as new information arrives.

## 35.3 Reference-to-Concept Mapping

| Concept | Recommended reference |
|---|---|
| Conversation/session memory | OpenAI Agents SDK Sessions [1] |
| Session persistence | OpenAI Agents SDK Sessions [1] |
| Long-term agent memory | OpenAI Agent Memory [2] |
| File/Markdown memory | OpenAI Agent Memory [2], Claude Code [5] |
| Project instructions | Claude Code [5] |
| Context compaction | OpenAI Compaction [3], Anthropic docs [6] |
| Working/agent state | LangGraph Checkpoints [7] |
| Persistent workflow state | LangGraph Checkpoints [7] |
| Long-term memory across tasks | Deep Agents [8] |
| Semantic memory | Zep integration [9], RAG [13] |
| Tool/reasoning loop | ReAct [10] |
| Experience memory | Generative Agents [11] |
| Reflection | Generative Agents [11] |
| Hierarchical memory | MemGPT [12] |
| Vector retrieval | RAG [13] |
| Dynamic/evolving memory | A-MEM [14] |
| Hybrid memory | OpenAI [1][2], LangChain [7][8][9] |

## 35.4 Suggested Core References for Thesis

Official implementation references:

1. OpenAI Agents SDK — Sessions [1]
2. OpenAI Agents SDK — Agent Memory [2]
3. Anthropic Claude Code — Project/Memory documentation [5]
4. LangGraph — Checkpointing [7]

Research references:

5. ReAct [10]
6. Generative Agents [11]
7. MemGPT [12]
8. RAG [13]
9. A-MEM [14]

## 35.5 Important Research Note

These references do not imply that every modern agent uses the same memory architecture. Different systems use different combinations of conversation history, structured state, files, Markdown, SQL/NoSQL, search, vector retrieval, summaries, compaction, and checkpoints.

Therefore, for a thesis it is more accurate to state:

> "Existing agent systems employ different combinations of conversational history, persistent state, external memory, retrieval, and context-management mechanisms."

rather than:

> "Traditional agents use vector databases for memory."
