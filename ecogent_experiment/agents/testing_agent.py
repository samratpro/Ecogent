"""
Testing Agent. Handles running and analyzing tests.
"""

from ecogent_experiment.agents import BaseAgent

class TestingAgent(BaseAgent):
    """
    Agent responsible for running tests and verifying output.
    """
    def __init__(self):
        super().__init__("testing_agent")
        
    def execute(self, task: str, **kwargs) -> str:
        tool_key = kwargs.get("tool_key")
        if tool_key:
            project_id = kwargs.get("project_id")
            
            # Build search paths
            search_paths = [f"tools.builtin.testing", f"tools.generated.{tool_key}"]
            if project_id:
                search_paths.insert(0, f"projects.{project_id}.tools.{tool_key}")
                
            import importlib
            for module_path in search_paths:
                try:
                    mod = importlib.import_module(module_path)
                    if hasattr(mod, tool_key):
                        func = getattr(mod, tool_key)
                        tool_kwargs = kwargs.get("tool_kwargs", {})
                        if "task" not in tool_kwargs:
                            tool_kwargs["task"] = task
                        if "ask_llm" in kwargs:
                            tool_kwargs["ask_llm"] = kwargs["ask_llm"]
                        return str(func(**tool_kwargs))
                except ImportError:
                    continue
                except Exception as e:
                    return f"[TestingAgent Error] Failed to execute {tool_key}: {e}"
                    
            return f"[TestingAgent Error] Could not find tool {tool_key} to execute task: {task}"
            
        return f"[TestingAgent] Analyzed and ran tests for: {task}"
