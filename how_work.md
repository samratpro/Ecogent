1. if user ask a request
if chat is new:
 1. direct community with LLM
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



--------------------------------------------------------
browser agentic task to reuse pattern:
--------------------------------------------------------

I want to implement if browser base task come base on that task it will create a pattern for that chat I mean for example a person said
go to amazon go this category check price of these products compare price and give me report

then 1 days later said to do same task again on that chat then agent can reuse that json workflow to reduce AI cost but json should have all I mean where to cick which to select where to fillup and validation check each steps
when reuse if any steps validation fail then communicate with AI again
this will do browser agent when a task base on browser