"""
Coding Agent. Handles code generation and modification.
"""

from ecogent_experiment.agents import BaseAgent

class CodingAgent(BaseAgent):
    """
    Agent responsible for writing and refactoring code.
    Typically escalates to the cloud for complex tasks.
    """
    def __init__(self, cloud_provider=None):
        super().__init__("coding_agent")
        self.cloud_provider = cloud_provider
        
    def execute(self, task: str, **kwargs) -> str:
        tool_key = kwargs.get("tool_key")
        if tool_key:
            project_id = kwargs.get("project_id")
            
            # Build search paths
            search_paths = [f"tools.builtin.code", f"tools.generated.{tool_key}"]
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
                    return f"[CodingAgent Error] Failed to execute {tool_key}: {e}"
        
        if self.cloud_provider:
            result = self.cloud_provider.generate_plan(task)
            return f"[CodingAgent Cloud] {result.get('answer', '')}"
            
        if tool_key:
            return f"[CodingAgent Error] Could not find tool {tool_key} to execute task: {task}"
            
        return f"[CodingAgent Local] Generated code for: {task}"
