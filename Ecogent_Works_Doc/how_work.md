## How it works:
Here is detail explain how Ecogent works:-

## Technology
- Python, can be use JS, Java etc
- Playwright, can be use selenium
- BeautifulSoup, can be used cheerio or others
- json files
- VectorDB(ChoromaDB)
- NOSQL DB (JSON)
- Tiny Local LLM
- browser manage - https://github.com/samratpro/playwright_browser_manager
-  DearPyGui  for GUI

## Builtin Tools
- File Operations tools

## Common Settings
- Temp folder
- Output/Selected Folder
- Headless or Graphics mode

```
Ecogent is a browser agent that target to reduce token cost by reusing previous and using some technique

Ecogent is a browser agent whose LLM usage decreases with reuse. We contribute (a) a fallback ladder for finding elements that uses as few tokens as possible, (b) plans that carry validation elements so only the broken steps get healed, and (c) reuse policies for each task type. On a benchmark of repeated tasks with deliberate site changes, we measure dollar cost, tokens and success rate over N runs against browser-use, a no-cache baseline and an AWM-style baseline.
```

### How initialized new task/chat:
- When a chat/task OPEN user will select which type of task it is i.e (Analysis, Data Scrap, Automation, Software Test, Others)
- If Ecogent Adapt with another agent or software from LLM tools call take confirmation Task type with Intent
- Once Select/Confirmed task, a chat/task window will open with plan.json, current_task.json, steps.json, chat-NOSQL (Unique for each chat)
- Need to send details on how Ecogent works to the LLM with a strong system prompt so that the LLM returns the structure of plan.json, current_task.json, steps.json, chat.json etc all for that specific project
- Now the agent is clear about the main task and which is main responsibilty to handle this task

## How to handle " Analysis " Task
```
Suppose a user asked for analysis a task and create summary.
Example user said "Search on Google Scholar with topic which paper worked with browser agent analysis and give me summerized docs or md file"
```
- With user prompt, system prompt, and all "analysis" related tools send to LLM
- LLM will created powerfull unique chat-NOSQL, plan.json, and current_task.json
- Agent will store current state summary in " chat-NOSQL " memory with LLM help
- Now Agent will execute step by step by current_task.json to fullfill plan.json

### current_task.json example got from LLM
```json
[{'step_name':'open scholar.google.com', 'tech':'playwright', 'action':'open_url', 'url':'scholar.google.com'},
{'step_name':'open google.com if fail url open search google', 'tech':'playwright', 'action':'open_url', 'url':'google.com'},
{'step_name':'find out search box', 'tech':'beautifulsoup','action':'get_page_data', 'url':'google.com'},
{'step_name':'click search field', 'tech':'playwright','action':'click', 'url':'google.com'},
{'step_name':'get page data', 'tech':'beautifulsoup','action':'get_page_data', 'url':'google.com****'},
................
]
```
### How execute agent will LLM
- Agent will use playwright to open browser
- Grab Page data with BeautifulSoup
- Use probable element find common filter with soup find_app example inputbox can find input and communicate with LLM
- if fail ommunicate with LLM again with more broader area
- if fail send all page data with soup exclude outlier data
- LLM gives where to click or what to do
- Agent can hold for user if any crutial info need i.e captcha, credentials, etc
- Each steps execute agent will update " plan.json " to rember
- In plan.json will keep also validation elements that will use for validation if it reuse 
- If this plan use for next run it will also selfhealing with LLM if validation fail
- This plan can have 3 part, destination, execution and keep each data in temp file
- After get all analysis data from source from temp file LLM will analysis and create a final output file that file format and data present user wanted, example JSON, docs, md, excel  so on.

#### what happen when user will do following up for this
```
Suppose user said I need some update data here or I need different format or mode deep analysis
```
- LLM will get existing plan, summary, necessary tools for this
- LLM will do healing if needs
- If LLM confirmed no healing needs then executive again same task, i.e some time user can say I need same type data but more deep info then the task is same info but more deep analysis from LLM



 ## How to handle " Scrapping " Task
```
Suppose user said " Visit Amazon and go on baby products category and scrap all product info of baby products category which price under $50" 
```
- With user prompt, system prompt, and all "Scrapping" related tools send to LLM
- LLM will created powerfull unique chat-NOSQL, plan.json, and current_task.json
- Agent will store current state summary in " chat-NOSQL " memory with LLM help
- Now Agent will execute step by step by current_task.json to fullfill plan.json

### current_task.json example got from LLM
```json
```
- Agent will open browser with playwright support and visit destination url and navigation target location with LMM tools support and agents Execution like data analysis way
- Decided how can be navigation and how can grab each single data record
- Decided when need stop
- After create a common "programetic pattern" it will take 10-20 sample data and keep record in excel csv or user expected file and format
- Now from LLM take final validation that data is comming user's expected format
- If fail and not coming user expected format  it will do healing of " programetic patter " for data scrapping part
- If all ok take from user confirmation that data is perfectly coming 
- If not ok if user said there is any problem do healing of " programetic patter " for data scrapping part or if need it will heal entire plan.json
- If all ok start scrapping and output final version of data 
- Track all record in plan.json with validation 

### what happen when user will do following up for this
```
Suppose user said I need some update data here or I need scrapping same or similar data for different category from Amazon
```
- LLM will get existing plan, summary, necessary tools for this
- LLM will do healing if needs
- If LLM confirmed no healing needs then executive again same task, i.e some time user can say I need scrap same data again


## How to handle " Automation " Task
```
Suppose user said " I need an Automation system that will apply Jobs for me when any Backend Development Jobs apear in LinkedIn" 
```
#### Warning
```
To execute Automation task most of the time 3 important thing we need ( 1. Credentials 2. User provide info to submit anywhere anything 3. A scheduling Feature to perform the automation task on specific time).

Most of the site comes with captcha or different kind of challenge. Also security issue is matter here, so agent can hold for user interaction, user will perform login or handle any kind of captcha challenge,  when user confirmed agent will store cookie to reuse later

And user will also tell agent which is destination folder or file to submit any info if need

Agent will comes with a periodic task execution feature
```

- 





