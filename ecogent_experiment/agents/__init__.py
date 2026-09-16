"""
Agent implementations for Ecogent.
"""

class BaseAgent:
    """Base class for all agents."""
    def __init__(self, name: str):
        self.name = name
        
    def execute(self, task: str, **kwargs) -> str:
        raise NotImplementedError
