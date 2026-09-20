# Traditional AI Agent Tool Calling — Detailed Architecture

## 1. Scope

This document explains the **traditional tool-using agent architecture**:

- how tools are pre-built
- how tools are registered
- how tool definitions are given to an LLM
- how system prompts and tool schemas work together
- how the LLM decides to call a tool
- how a tool call is represented
- how the runtime executes the tool
- how tool results return to the LLM
- how multiple tool calls form an agent loop
- how built-in tools differ from custom tools
- how MCP fits into the architecture
- how errors, validation, permissions, and tool choice are handled
- how a new project and an existing project differ
- what is actually "LLM", "agent", "tool", and "runtime"

The examples use conceptual JSON and Python-like pseudocode. Exact request/response schemas differ between model providers.

---

# 2. The Core Idea

A traditional tool-using agent is not simply:

```text
User
 ↓
LLM
 ↓
Answer
```

It is closer to:

```text
User
 ↓
Agent Runtime
 ↓
Build model context
 ↓
LLM
 ↓
Decision
 ↓
Tool call OR final answer
 ↓
If tool call:
    Runtime executes tool
    ↓
    Tool result
    ↓
    Update state/context
    ↓
    LLM again
 ↓
Final answer
```

The key separation is:

> **The LLM chooses an action; the agent runtime executes the action.**

The model does not normally execute `read_file()` or `run_tests()` by itself.

---

# 3. Main Components

```text
                         USER
                           |
                           v
                 +--------------------+
                 |    Agent Runtime   |
                 +----------+---------+
                            |
          +-----------------+-----------------+
          |                 |                 |
          v                 v                 v
   System Prompt      Conversation       Tool Registry
                        / State
          |                 |                 |
          +-----------------+-----------------+
                            |
                            v
                    +---------------+
                    | Context Build |
                    +-------+-------+
                            |
                            v
                          LLM
                            |
                 +----------+----------+
                 |                     |
                 v                     v
             Final Answer          Tool Call
                                       |
                                       v
                                  Tool Runtime
                                       |
                                       v
                                  Tool Result
                                       |
                                       v
                                 State Update
                                       |
                                       v
                                  Context Build
                                       |
                                       v
                                      LLM
```

---

# 4. What Is a Tool?

A tool is an externally executable capability that the model can request.

Examples:

```text
read_file
write_file
edit_file
search_code
run_command
run_tests
web_search
database_query
send_email
browser_click
```

A tool normally has two sides:

```text
Tool
|
+-- Definition / schema
|
+-- Actual implementation
```

The **definition** tells the LLM what the tool does and what arguments it accepts.

The **implementation** is executed by the agent runtime.

---

# 5. Tool Definition

A conceptual tool definition:

```json
{
  "name": "read_file",
  "description": "Read the contents of a file in the current project.",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Path of the file to read."
      }
    },
    "required": ["path"]
  }
}
```

The model needs:

```text
name
description
input schema
```

It does not need the actual Python implementation.

For example, the implementation could be:

```python
def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
```

The model does not execute this Python code.

The runtime does.

---

# 6. Pre-built Tools

A traditional agent usually has a set of tools prepared before the user asks a question.

For a coding agent:

```text
Tool Registry
|
+-- read_file
+-- write_file
+-- edit_file
+-- list_directory
+-- search_code
+-- run_command
+-- run_tests
+-- git_diff
+-- git_status
```

These can be:

- built into the application
- implemented by the developer
- supplied by an SDK/framework
- provided by a remote tool server such as MCP

The tool itself can be ordinary application code.

Example:

```python
def search_code(query: str):
    ...
```

Then the application registers it with the agent.

---

# 7. Built-in Tools vs Custom Tools

## Built-in tools

These are capabilities provided by the model/API/platform.

Examples can include:

```text
Web search
File search
Computer/browser capabilities
Provider-managed retrieval
```

The provider controls much of the implementation.

## Custom/function tools

These are functions supplied by the application developer.

Example:

```python
def get_customer(customer_id):
    ...
```

The application owns the implementation.

Conceptually:

```text
                 Tools
                   |
          +--------+--------+
          |                 |
          v                 v
      Built-in          Custom
      provider          function
          |                 |
          v                 v
      Provider          Your code
```

OpenAI's API documentation distinguishes built-in tools from custom function tools. Anthropic likewise documents tool definitions with names, descriptions, and JSON Schema input definitions.

---

# 8. How the LLM Learns About Tools

The runtime sends tool definitions as part of the model request.

Conceptually:

```json
{
  "model": "some-model",
  "input": [
    {
      "role": "system",
      "content": "You are a coding agent."
    },
    {
      "role": "user",
      "content": "Read auth/views.py."
    }
  ],
  "tools": [
    {
      "name": "read_file",
      "description": "Read a project file.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string"
          }
        },
        "required": ["path"]
      }
    }
  ]
}
```

The exact API schema varies, but the concept is the same:

```text
System instructions
+
User request
+
Available tools
        ↓
       LLM
```

Anthropic's documentation explicitly describes tool definitions using a tool name, description, and `input_schema`, and notes that tool definitions contribute to the tool-use instructions provided to the model.

OpenAI's API documentation similarly defines function tools with a name, description, and JSON Schema parameters.

---

# 9. Tool Description Matters

The model chooses tools based partly on the information in their definitions.

Bad:

```text
{
  "name": "search"
}
```

Better:

```text
{
  "name": "search_code",
  "description": "Search source files in the current project for a text pattern, symbol, class, function, or import.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "The code symbol, text pattern, or search phrase."
      }
    },
    "required": ["query"]
  }
}
```

A good description tells the model:

1. What the tool does
2. When it should be used
3. What it should not be used for
4. What each argument means
5. What the result represents
6. Important limitations

Anthropic's official tool-use documentation specifically emphasizes detailed tool descriptions and parameter descriptions as important for reliable tool selection.

---

# 10. System Prompt + Tools

Tools are not the entire agent instruction.

The agent can also have a system/developer prompt.

Example:

```text
You are a coding agent.

Rules:

1. Inspect relevant files before modifying them.
2. Use search_code before reading unknown files when appropriate.
3. Do not invent file contents.
4. Run tests after significant code changes.
5. Do not execute destructive commands without authorization.
6. Use the available tools when they are appropriate.
```

Then the tool definitions are supplied separately.

Conceptually:

```text
                LLM INPUT
                   |
       +-----------+-----------+
       |                       |
       v                       v
 System Instructions      Tool Definitions
       |                       |
       +-----------+-----------+
                   |
                   v
                 User
                   |
                   v
                  LLM
```

The model combines these sources when deciding what to do.

---

# 11. Important: The LLM Does Not Usually Need Hardcoded Routing

A common beginner architecture is:

```python
if "weather" in user_input:
    call_weather()

elif "file" in user_input:
    call_read_file()
```

That is not necessary for a general tool-calling agent.

Instead:

```text
User request
     ↓
LLM sees tool definitions
     ↓
LLM determines which tool is appropriate
     ↓
Structured tool call
```

For example:

```text
User:
"Open auth/views.py"

LLM:
read_file(path="auth/views.py")
```

The model is responsible for selecting among the available tools.

The runtime is responsible for safely executing the selected tool.

---

# 12. Tool Calling: First Model Call

Suppose:

```text
USER:
Read auth/views.py and explain the login implementation.
```

Available:

```text
read_file
search_code
edit_file
run_tests
```

The first model call might conceptually produce:

```json
{
  "type": "tool_call",
  "name": "read_file",
  "arguments": {
    "path": "auth/views.py"
  }
}
```

Some APIs represent the call using a separate call ID.

For example:

```json
{
  "id": "call_001",
  "type": "tool_call",
  "name": "read_file",
  "arguments": {
    "path": "auth/views.py"
  }
}
```

The exact field names vary by provider.

---

# 13. What Happens After the Tool Call?

The LLM does not directly run:

```python
read_file(...)
```

Instead:

```text
LLM
 |
 | tool call
 v
Agent Runtime
 |
 | validate tool name
 | validate arguments
 | check permissions
 |
 v
Tool implementation
 |
 v
File system
```

The runtime may perform:

```text
1. Find tool by name
2. Validate arguments
3. Check permissions
4. Execute tool
5. Catch errors
6. Format result
7. Add result to agent state
```

---

# 14. Tool Result

Suppose:

```python
read_file("auth/views.py")
```

returns:

```python
def login(request):
    ...
```

The runtime sends the result back as a tool-result item.

Conceptually:

```json
{
  "type": "tool_result",
  "tool_call_id": "call_001",
  "content": "def login(request): ..."
}
```

Then the next LLM call has access to:

```text
User request
+
Tool call
+
Tool result
+
System instructions
+
Available tools
```

---

# 15. The Two-Phase Tool Calling Pattern

A simple traditional implementation is:

### Phase 1 — Ask the LLM

```text
User
 ↓
LLM
 ↓
Tool call
```

### Phase 2 — Execute and return

```text
Tool call
 ↓
Runtime
 ↓
Tool
 ↓
Tool result
 ↓
LLM
```

Then the LLM can either:

```text
Final answer
```

or:

```text
Another tool call
```

LangChain's tool-calling documentation demonstrates this pattern explicitly: obtain the model's tool calls, execute the selected tools, append tool results to the message sequence, and invoke the model again.

---

# 16. Complete Agent Tool Loop

```text
                    USER
                      |
                      v
             +----------------+
             | Context Builder |
             +-------+--------+
                     |
                     v
                    LLM
                     |
             +-------+-------+
             |               |
             v               v
        Final Answer      Tool Call
                              |
                              v
                       Agent Runtime
                              |
                    +---------+---------+
                    |                   |
                    v                   v
               Validation          Permission
                    |                   |
                    +---------+---------+
                              |
                              v
                            Tool
                              |
                              v
                         Tool Result
                              |
                              v
                     Update Agent State
                              |
                              v
                       Context Builder
                              |
                              v
                             LLM
                              |
                         ...repeat...
```

---

# 17. Multiple Tool Calls

The model may request multiple tools.

For example:

```text
User:
What is the weather in Dhaka and what is 25 * 4?
```

The model could produce:

```json
[
  {
    "name": "get_weather",
    "arguments": {
      "location": "Dhaka"
    }
  },
  {
    "name": "calculate",
    "arguments": {
      "expression": "25 * 4"
    }
  }
]
```

The runtime can execute them sequentially or, when supported and safe, in parallel.

Modern tool protocols such as MCP explicitly support tool calling and can support parallel tool execution in appropriate implementations.

---

# 18. Tool Choice

The application can sometimes control whether tools may be called.

Conceptually:

```text
tool_choice = auto
```

means:

```text
LLM decides
```

while:

```text
tool_choice = required
```

can require tool use where the provider supports it.

And:

```text
tool_choice = none
```

prevents tool use.

The exact options vary by provider/model.

LangChain documentation provides examples of `auto`, `required`, and `none` for compatible model integrations.

---

# 19. Tool Arguments Are Structured

Suppose:

```text
Tool:
get_weather
```

Schema:

```json
{
  "type": "object",
  "properties": {
    "location": {
      "type": "string"
    },
    "unit": {
      "type": "string",
      "enum": ["celsius", "fahrenheit"]
    }
  },
  "required": ["location", "unit"]
}
```

The model should produce arguments matching the schema:

```json
{
  "location": "Dhaka",
  "unit": "celsius"
}
```

This is much safer than asking the LLM to output arbitrary text such as:

```text
CALL WEATHER Dhaka Celsius
```

Modern APIs can support strict schema adherence for function calls.

---

# 20. What Does "Pre-built Tool" Actually Mean?

A pre-built tool can be:

```text
Developer-created
Provider-created
Framework-created
Remote-service-created
```

Example:

```python
@tool
def get_weather(city: str):
    return weather_api(city)
```

The developer created the implementation.

The agent system creates or registers the tool schema.

Then:

```text
Python function
       |
       v
Tool registration
       |
       v
Tool schema
       |
       v
LLM
```

The model never needs the source code of the Python function.

---

# 21. Tool Registry

A traditional agent runtime can maintain something like:

```python
tools = {
    "read_file": read_file,
    "edit_file": edit_file,
    "search_code": search_code,
    "run_tests": run_tests
}
```

And separately expose schemas:

```python
tool_schemas = [
    {
        "name": "read_file",
        "description": "...",
        "parameters": {...}
    },
    {
        "name": "edit_file",
        "description": "...",
        "parameters": {...}
    }
]
```

Then:

```text
LLM sees:
tool_schemas

Runtime owns:
tools implementations
```

This distinction is fundamental.

---

# 22. Tool Registry vs LLM

The LLM does not normally "own" the tools.

Instead:

```text
                  Agent Runtime
                  /            \
                 /              \
                v                v
          Tool Registry        LLM
                |                |
                |                |
         implementations    tool schemas
                |                |
                +-------+--------+
                        |
                        v
                  Tool selection
```

The LLM chooses a tool name and arguments.

The runtime maps that tool name to the actual implementation.

---

# 23. Tool Errors

A tool can fail.

Example:

```text
LLM
 ↓
read_file("missing.py")
 ↓
Tool
 ↓
FileNotFoundError
```

The runtime should turn that into a structured tool result:

```json
{
  "type": "tool_result",
  "tool_call_id": "call_002",
  "error": true,
  "content": "File not found: missing.py"
}
```

The LLM then receives the error and can recover:

```text
Tool failed
   ↓
LLM
   ↓
Try list_directory
   ↓
Find correct file
   ↓
read_file(correct_file)
```

This is one reason the tool loop is more powerful than a single model response.

---

# 24. Tool Validation

Before execution:

```text
Tool call
   |
   v
Is tool name valid?
   |
   v
Are arguments valid?
   |
   v
Is user/agent authorized?
   |
   v
Is operation allowed?
   |
   v
Execute
```

For example:

```text
delete_database()
```

should not be treated the same as:

```text
read_file()
```

A production runtime can attach permission and risk information.

---

# 25. Read-only vs Destructive Tools

Tools can have different risk levels.

```text
Low risk:
read_file
search_code
git_status

Medium:
edit_file
write_file

High:
delete_file
run_shell_command
deploy
send_email
transfer_money
```

A mature agent runtime can use policies:

```text
read_file
    → execute automatically

edit_file
    → execute automatically or review

delete_database
    → require confirmation
```

MCP has tool annotations intended to describe characteristics such as read-only, destructive, or idempotent behavior, although annotations are hints and should not be treated as a complete security boundary.

---

# 26. MCP and Traditional Tool Calling

Model Context Protocol (MCP) is an important modern standard for connecting AI applications to external tools and resources.

Instead of embedding every tool implementation directly inside the agent:

```text
Agent
 |
 +-- local tool
 +-- local tool
 +-- local tool
```

MCP allows:

```text
Agent / MCP Client
       |
       v
   MCP Server
       |
       +-- tool
       +-- tool
       +-- resource
       +-- prompt
```

For example:

```text
Coding Agent
      |
      v
MCP server
      |
      +-- GitHub
      +-- Database
      +-- Files
      +-- Browser
```

The model-facing concept remains:

```text
Tool name
Description
Input schema
```

The protocol standardizes how the client and server communicate.

The current MCP specification (2026-07-28) defines tool calls using structured requests and JSON Schema-based tool input/output schemas.

---

# 27. MCP Does Not Replace the LLM

This is important.

MCP is not:

```text
MCP = LLM
```

It is:

```text
LLM
 |
Agent / MCP Client
 |
MCP protocol
 |
MCP Server
 |
Tool
```

The model still decides what tool to request.

The MCP infrastructure provides a standardized way to expose and invoke tools/resources.

---

# 28. New Chat + New Project Example

User:

```text
Create a Django login system.
```

Project:

```text
myproject/
├── manage.py
├── settings.py
├── users/
└── requirements.txt
```

Agent has pre-built tools:

```text
list_directory
read_file
search_code
edit_file
run_command
run_tests
```

## Step 1 — Build context

```text
System:
You are a coding agent...

User:
Create a Django login system.

Tools:
list_directory
read_file
search_code
edit_file
run_command
run_tests
```

## Step 2 — LLM decides

```json
{
  "name": "list_directory",
  "arguments": {
    "path": "."
  }
}
```

## Step 3 — Runtime executes

```text
list_directory(".")
```

Result:

```text
manage.py
settings.py
users/
requirements.txt
```

## Step 4 — Result becomes context

```text
System
+
User
+
Tool call
+
Tool result
+
Tools
```

## Step 5 — LLM calls another tool

```json
{
  "name": "read_file",
  "arguments": {
    "path": "settings.py"
  }
}
```

Then:

```text
read_file
 ↓
settings.py contents
 ↓
LLM
```

The agent continues until the login system is implemented and tested.

---

# 29. Existing Chat + Existing Project Example

Previous conversation:

```text
User:
Add OTP authentication.

Agent:
Implemented OTP.

Tool:
edit_file(...)

Tool:
run_tests(...)

Agent:
Tests passed.
```

Later the user says:

```text
OTP is failing again.
```

The agent may have:

```text
System instructions
+
Relevant conversation history
+
Current project files
+
Current task state
+
Tool definitions
```

The LLM might first request:

```json
{
  "name": "search_code",
  "arguments": {
    "query": "OTP verification"
  }
}
```

Result:

```text
users/otp.py
users/views.py
users/tests.py
```

Then:

```json
{
  "name": "read_file",
  "arguments": {
    "path": "users/otp.py"
  }
}
```

Then perhaps:

```json
{
  "name": "run_tests",
  "arguments": {
    "path": "users/tests.py"
  }
}
```

The tool results are fed back into the current context, and the LLM decides the next action.

---

# 30. Where Does the Tool Call Live?

During an execution loop, the tool call is part of the model/runtime state.

Conceptually:

```text
Messages / state

1. User
   "OTP is failing"

2. Assistant
   tool_call: search_code

3. Tool
   result: users/otp.py

4. Assistant
   tool_call: read_file

5. Tool
   result: file contents

6. Assistant
   tool_call: run_tests

7. Tool
   result: test failure

8. Assistant
   final answer
```

This history allows the LLM to understand what actions have already happened.

---

# 31. Tool Result Is Not Automatically Long-Term Memory

This distinction is important.

Suppose:

```text
run_tests()
```

returns:

```text
3 tests passed.
```

That result is useful for the current task.

It does not necessarily need to become:

```text
Permanent memory forever
```

Instead:

```text
Tool result
   |
   v
Current working context
   |
   v
Task completes
   |
   v
Possibly summarized/persisted if useful
```

This connects directly to the memory architecture from the previous document.

---

# 32. Context Size and Tool Definitions

Tools themselves consume model context/input.

If an agent has:

```text
200 tools
```

and every tool has a long description and schema, sending all of them on every model call can become expensive.

The model provider documentation explicitly counts tool definitions/schema as input to the model for tool-use requests.

Therefore a mature system may use:

```text
All available tools
       |
       v
Tool selection/filtering
       |
       v
Relevant tool definitions
       |
       v
LLM
```

This is highly relevant to your research direction.

---

# 33. Traditional Tool Architecture

The basic traditional architecture can therefore be represented as:

```text
                    TOOL SYSTEM
                         |
        +----------------+----------------+
        |                                 |
        v                                 v
 Tool Registry                       Tool Schema
        |                                 |
        v                                 v
Actual Function                    LLM-visible
Implementation                      Definition
        |                                 |
        +----------------+----------------+
                         |
                         v
                    Agent Runtime
                         |
                         v
                         LLM
                         |
                   Tool Selection
                         |
                         v
                   Structured Call
                         |
                         v
                   Tool Execution
                         |
                         v
                    Tool Result
                         |
                         v
                    Agent State
                         |
                         v
                  Next LLM Call
```

---

# 34. Traditional Tool Calling vs Your Research Direction

Traditional:

```text
All/selected tool schemas
          +
Current context
          ↓
         LLM
          ↓
      Tool call
          ↓
       Runtime
```

Your proposed research can investigate:

```text
Large tool registry
       ↓
Semantic tool retrieval
       ↓
Relevant tools only
       ↓
Smaller tool context
       ↓
LLM
```

This is a **different research question from memory retrieval**, but it fits naturally with your overall cost-aware agent architecture.

You can measure:

```text
Number of tools exposed
+
Tool-schema tokens
+
LLM input tokens
+
Tool-selection accuracy
+
Task success
+
Latency
+
Cost
```

---

# 35. Key Terminology

## LLM

The reasoning/model component.

```text
Input context
    ↓
LLM
    ↓
Answer or structured action
```

## Tool

An executable capability.

```text
read_file()
search_code()
run_tests()
```

## Tool schema

The model-visible description of a tool.

```text
name
description
input schema
```

## Agent runtime

The controller around the LLM.

It handles:

```text
context
tool execution
state
errors
permissions
loops
termination
```

## Tool registry

The runtime's collection of available tools and their implementations/schemas.

## Tool call

The LLM's structured request to invoke a particular tool with arguments.

## Tool result

The output/error returned by the runtime after executing the tool.

---

# 36. Complete Traditional Agent Tool-Calling Flow

```text
                           USER
                             |
                             v
                    +----------------+
                    | Agent Runtime  |
                    +-------+--------+
                            |
              +-------------+-------------+
              |                           |
              v                           v
       System Prompt                Tool Registry
              |                           |
              |                     +-----+-----+
              |                     |           |
              |                     v           v
              |                  Schemas   Implementations
              |                     |
              +----------+----------+
                         |
                         v
                  Context Builder
                         |
                         v
                        LLM
                         |
              +----------+----------+
              |                     |
              v                     v
        Final Response          Tool Call
                                    |
                                    v
                              Validate Call
                                    |
                                    v
                              Check Policy
                                    |
                                    v
                              Execute Tool
                                    |
                                    v
                              Tool Result
                                    |
                                    v
                           Update Agent State
                                    |
                                    v
                           Context Builder
                                    |
                                    v
                                   LLM
                                    |
                               ...repeat...
                                    |
                                    v
                              Final Response
```

---

# 37. Important Conclusions

### 1. Tools are normally pre-built or registered capabilities

The LLM does not magically create the executable implementation every time.

### 2. The LLM sees a tool schema

Usually:

```text
name
description
input schema
```

### 3. The LLM chooses the tool

The runtime generally does not need hardcoded keyword rules.

### 4. The runtime executes the tool

```text
LLM chooses
Runtime executes
```

### 5. Tool results become current context/state

They are returned to the LLM so it can continue reasoning.

### 6. Tool calling is iterative

```text
LLM
→ tool
→ result
→ LLM
→ tool
→ result
→ LLM
→ final
```

### 7. Tool definitions themselves consume context

Large tool registries can increase input-token usage.

### 8. Tool results do not automatically become permanent memory

Current execution state and long-term memory are separate concepts.

### 9. MCP standardizes external tool connectivity

It does not replace the LLM or agent runtime.

### 10. The fundamental architecture is

```text
                LLM
                 |
          chooses an action
                 |
                 v
             Tool Call
                 |
                 v
          Agent Runtime
                 |
                 v
              Tool
                 |
                 v
            Tool Result
                 |
                 v
              LLM
```

---

# 38. References

## Official Documentation

### [1] OpenAI — API Quickstart / Tools

OpenAI documentation showing how models can be extended with built-in tools and custom function tools.

https://platform.openai.com/docs/quickstart/make-your-first-api-request

Relevant for:
- Built-in tools
- Function tools
- Tool-enabled model requests

### [2] OpenAI — API Reference: Tools / Function Calling

OpenAI API reference documenting tool definitions, function names, descriptions, JSON Schema parameters, strict schema adherence, and tool choice.

https://platform.openai.com/docs/api-reference/chat/object

Relevant for:
- Tool schemas
- Function calling
- JSON Schema
- Strict argument validation
- Tool choice

### [3] Anthropic — Implement Tool Use

Anthropic's official tool-use implementation documentation.

https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use

Relevant for:
- Tool definitions
- `name`
- `description`
- `input_schema`
- Tool-use system instructions
- Tool descriptions
- Tool argument schemas

### [4] Anthropic — Prompting Best Practices

Anthropic documentation discussing tool usage and explicit action-oriented instructions.

https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables

Relevant for:
- System prompting
- Tool use
- Tool-triggering behavior
- Agent instructions

### [5] LangChain — Tool Calling

LangChain documentation/examples describing binding tools to models and processing returned tool calls.

https://docs.langchain.com/

Relevant for:
- Tool binding
- Tool schemas
- `tool_calls`
- Tool messages
- Tool execution loops

### [6] LangChain — Llama.cpp Tool Calling

Concrete LangChain documentation showing OpenAI-style tool schemas and tool calling.

https://docs.langchain.com/oss/python/integrations/chat/llamacpp/

Relevant for:
- Local LLM tool calling
- Tool schemas
- JSON Schema
- Tool binding
- Function/tool calling

### [7] Model Context Protocol — 2026-07-28 Specification

Official MCP specification release documentation.

https://blog.modelcontextprotocol.io/posts/2026-07-28/

Relevant for:
- Standardized tool calls
- Tool schemas
- Stateless tool communication
- Tool discovery
- Multi-round-trip requests
- Tasks
- Tool routing

### [8] Model Context Protocol — TypeScript SDK

Official MCP SDK documentation.

https://ts.sdk.modelcontextprotocol.io/v2/

Relevant for:
- MCP servers
- Tools
- Resources
- Prompts
- MCP clients
- Connecting AI applications to external systems

---

## Research References

### [9] ReAct

S. Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models," arXiv:2210.03629, 2022.

https://arxiv.org/abs/2210.03629

Relevant for:

```text
Reasoning
   ↓
Action
   ↓
Observation
   ↓
Reasoning
```

It provides a foundational academic model for interleaving reasoning with external actions.

### [10] Toolformer

T. Schick et al., "Toolformer: Language Models Can Teach Themselves to Use Tools," Advances in Neural Information Processing Systems (NeurIPS), 2023.

https://arxiv.org/abs/2302.04761

Relevant for:
- Language models learning to use external tools
- Tool invocation
- API interaction
- Tool-use training

### [11] MRKL Systems

E. Karpas et al., "MRKL Systems: A Modular, Neuro-Symbolic Architecture That Combines Large Language Models, External Knowledge Sources and Discrete Reasoning," arXiv:2205.00445, 2022.

https://arxiv.org/abs/2205.00445

Relevant for:
- Modular architectures
- LLM routing
- External tools/knowledge
- Neuro-symbolic agent design

---

# 39. Reference-to-Concept Mapping

| Concept | Main reference |
|---|---|
| Tool definition | OpenAI [2], Anthropic [3] |
| Tool name/description/schema | Anthropic [3] |
| Function calling | OpenAI [2] |
| Strict JSON Schema arguments | OpenAI [2] |
| Built-in tools | OpenAI [1] |
| Custom tools | OpenAI [1][2] |
| Tool selection | OpenAI [2], Anthropic [3] |
| Tool execution loop | ReAct [9] |
| Tool result → next LLM call | LangChain [5][6] |
| Local LLM tool calling | LangChain Llama.cpp [6] |
| Standardized external tools | MCP [7][8] |
| Tool discovery | MCP [7][8] |
| Tool-server architecture | MCP [7][8] |
| Tool-use training | Toolformer [10] |
| Modular tool routing | MRKL [11] |
| Reasoning + action | ReAct [9] |

---

# 40. Final Mental Model

If you remember only one architecture, use this:

```text
                         USER
                           |
                           v
                    Agent Runtime
                           |
             +-------------+-------------+
             |                           |
             v                           v
       System Prompt               Tool Registry
             |                           |
             |                      Tool Schemas
             |                           |
             +-------------+-------------+
                           |
                           v
                    Context Builder
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
                              Agent Runtime
                                      |
                                      v
                                    Tool
                                      |
                                      v
                                Tool Result
                                      |
                                      v
                              State / Context
                                      |
                                      v
                              Context Builder
                                      |
                                      v
                                     LLM
                                      |
                                  Repeat
                                      |
                                      v
                                  Answer
```

The most important distinction for your thesis is:

```text
LLM
= decides

Agent Runtime
= controls

Tool
= executes

Tool Schema
= tells the LLM what is available

Context
= information given to the LLM

State
= information maintained by the runtime
```
