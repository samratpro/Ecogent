1. if user ask a request
if chat is new:
 1. direct communicate with High cost LLM
 2. make plan.json (hold main task and sub tasks)
 3. then agent + local tiny llm will pass
    i. prebuild tools info
    ii. if existing tools made already for that project, that info
    iii. pass steps number n
    iv.  if prebuild tools, existing tools made already for that project, work only otherwise llm return tools
    v. agent create that tools and execute
    vi. when execute steps agent will commmunicate with llm if need
    vii. verify by LLM that steps complete
4. main target is 3 target to reduce token cost
   i. main plan(with all task sub task will have as json file, and keys will store in vector db to quickly retrive task), prebuild tools info, made tools for specific project info in vector db to quickly retrive. And to avoid repeating same task and pass a huge context it will help
   ii. A local supervisor help agent be more smart
   iii. all necessary common tools should premade



my research areas are:
1. ChromaDB/vectordb for memory management and efficient context building without lossing/compressing contex (chromadb store sementic key and metadata but json workflow or info will have in JSON base or NOSQL db ) 
2. Reuse previously done tasks if possible; for example, a browser agent can do it with keep navigate class ID and steps memorized; to achieve this, make some specialized agents that can efficiently handle specific tasks, e.g., coding, browser, os, test
3. Reuse previously made or built-in tools while keeping tool data in a vector DB easily retrievable 
4. Use a tiny LLM to handle tiny tasks; example: previous task matching, tool selection accuracy, specialized agent selection
5. If the tiny LLM totally fails, future implement take diffculty score more tiny LLM and router - low cost, mid cost and high cost llm  (but tiny LLM is testing stage now)
--------------------------------------------------------
browser agentic task to reuse pattern:
--------------------------------------------------------

I want to implement if browser base task come base on that task it will create a pattern for that chat I mean for example a person said
go to amazon go this category check price of these products compare price and give me report

then 1 days later said to do same task again on that chat then agent can reuse that json workflow to reduce AI cost but json should have all I mean where to cick which to select where to fillup and validation check each steps
when reuse if any steps validation fail then communicate with AI again
this will do browser agent when a task base on browser

--------------------------
coding agent
----------------------

GUI Automation - example pyautogui mentioned in last citetion



## Manual:
### Structure
- Local supervisor
- Tiny Local LLM
- VectorDB(ChoromaDB)
- NOSQL DB (JSON)
- Main plan.json for each chat (Unique for each chat)
- current_task.json (Unique for each chat)
- chat.json for chat history (Unique for each chat)
- prebuilt tools (for all chats)
- project-made tools by LLM (unique for each project)
- project_tools.json for tools history, manual, and location, and so on all(unique for each project)
- cloud LLM(API base ollama, openrouter, openai)
- multi-agent (Browser, Coding, Testing, OS task)
- browser_task.json (Unique for each chat)
- coding_task.json (Unique for each chat)
- testing_task.json (Unique for each chat)
- os_task.json (Unique for each chat)

## How it works:
Here is detail explain how Ecogent works:-

### How to work for a new task/chat:
- When task is new create initialized plan.json, current_task.json, chat.json, browser_task.json, coding_task.json, testing_task.json, os_task.json (Unique for each chat)
- Need to send details on how Ecogent works to the LLM with a strong system prompt so that the LLM returns the structure of plan.json, current_task.json, chat.json, browser_task.json, coding_task.json, testing_task.json, os_task.json etc all for that specific project
- Now the agent is clear about the task type and which Sub-Agent is main responsibilty to handle this task

#### How to handle browser-based task
- If the task is browser-based
- Also, the agent has current_task.json to complete that task where has all steps
- If the task is browser-based, then each task will have the following structure with browser automation:
    i. steps = []  
    ii. task_type = "browser"
    iii. current_step = 1
    iv. status = "pending"
    v. sub_agents = ["browser"]
    - When working browser_agent it will create that browser_task.json to record workflow
    - browser_task.json should be unique based on the chat and the current prompt
    - For example, the user said, " Please visit Amazon, search for iPhone, check price, compare with other site, and write report, here is that JSON workflow
        {
            "chat_id": "123456789",
            "task_id": "123456789",
            "task_type": "browser",
            "steps": [],
            "current_step": 1,
            "status": "pending",
            "sub_agents": ["browser"]
        }
   -
