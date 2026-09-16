"""
Mock Cloud LLM Provider for testing the architecture without hitting real APIs.
"""

import time
from typing import Any, Dict

from ecogent_experiment.providers.cloud import CloudLLMProvider


class MockCloudProvider(CloudLLMProvider):
    """
    Simulates a cloud LLM for escalated tasks.
    Returns deterministic or simple generated answers and mock token counts.
    """

    def __init__(self, simulate_latency_ms: int = 500):
        super().__init__(model_name="mock-cloud-model")
        self.simulate_latency_ms = simulate_latency_ms

    def verify(self) -> tuple[bool, str]:
        return False, "You are using the 'mock' provider. Real cloud APIs will not be called."

    def generate_plan(self, task: str) -> Dict[str, Any]:
        """Simulate generating a complex plan."""
        
        if self.simulate_latency_ms > 0:
            time.sleep(self.simulate_latency_ms / 1000.0)
            
        # Very basic mocking logic based on keywords
        task_lower = task.lower()
        
        if "python" in task_lower or "code" in task_lower:
            answer = "Here is a Python script to do that:\n```python\nprint('Hello World')\n```"
        elif "browser" in task_lower or "scrape" in task_lower or "web" in task_lower:
            answer = "I would launch a browser and navigate to the requested URL to extract the data."
        else:
            answer = f"I've analyzed the complex request '{task}' and developed a comprehensive plan to resolve it."
            
        # Simulate token counts
        input_tokens = len(task.split()) * 2 + 50
        output_tokens = len(answer.split()) * 2
        
        return {
            "answer": answer,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": self.model_name
        }
