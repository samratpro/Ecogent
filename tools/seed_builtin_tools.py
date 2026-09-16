import os
from ecogent_experiment.tool_registry import ToolRegistry

def seed_tools():
    # Assuming script is in the `tools` directory, project root is one level up
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chroma_dir = os.path.join(root, "data", "chroma")
    registry = ToolRegistry(chroma_dir)
    
    tools = [
        {
            "tool_key": "web_search",
            "natural_name": "Web Search",
            "description": "Search the internet or Google for information to find answers or latest news.",
            "category": "web",
            "agent": "browser_agent"
        },
        {
            "tool_key": "browse_website",
            "natural_name": "Browse Website",
            "description": "Navigate to a specific URL and read its text contents.",
            "category": "web",
            "agent": "browser_agent"
        },
        {
            "tool_key": "run_shell_command",
            "natural_name": "Run Shell Command",
            "description": "Execute a bash or shell command on the local system terminal.",
            "category": "system",
            "agent": "os_agent"
        },
        {
            "tool_key": "lint_code",
            "natural_name": "Lint Code",
            "description": "Check Python code for syntax errors without running it.",
            "category": "code",
            "agent": "coding_agent"
        },
        {
            "tool_key": "format_code",
            "natural_name": "Format Code",
            "description": "Format Python source code to standard style.",
            "category": "code",
            "agent": "coding_agent"
        },
        {
            "tool_key": "git_status",
            "natural_name": "Git Status",
            "description": "Check the status of the current git repository.",
            "category": "system",
            "agent": "os_agent"
        },
        {
            "tool_key": "git_commit",
            "natural_name": "Git Commit",
            "description": "Commit all tracked changes in git with a message.",
            "category": "system",
            "agent": "os_agent"
        },
        {
            "tool_key": "ping_host",
            "natural_name": "Ping Host",
            "description": "Ping a host or IP address to check network connectivity.",
            "category": "network",
            "agent": "os_agent"
        }
    ]
    
    for t in tools:
        registry.register_tool(
            tool_key=t["tool_key"],
            natural_name=t["natural_name"],
            description=t["description"],
            category=t["category"],
            agent=t["agent"],
            collection="builtin_tools"
        )
        print(f"Registered {t['tool_key']}")
        
if __name__ == "__main__":
    seed_tools()
    print("Done seeding built-in tools.")
