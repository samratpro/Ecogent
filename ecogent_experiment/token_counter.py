"""
Token counting suite for evaluating the token usage of the Ecogent architecture.
"""

import json
import os
import time

from ecogent_experiment.supervisor import Supervisor
from ecogent_experiment.router import Router
from ecogent_experiment.providers.mock_cloud import MockCloudProvider

def load_tasks(filepath: str) -> list[dict]:
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        return json.load(f)

def run_token_counter(tasks_file: str):
    """Run token counter against the Ecogent architecture."""
    print("Starting Ecogent Architecture Token Counter...")
    tasks = load_tasks(tasks_file)
    
    # Setup
    cloud_provider = MockCloudProvider(simulate_latency_ms=10)
    # Using tiny_llm=None for this counter to test rules -> cloud fallback mainly
    supervisor = Supervisor(tiny_llm=None, confidence_threshold=0.7)
    
    # Mock local tool execution
    def mock_tool_executor(tool_name, **kwargs):
        time.sleep(0.01)
        return f"Executed {tool_name}"
        
    router = Router(tool_executor=mock_tool_executor, cloud_provider=cloud_provider)
    
    results = []
    
    total_input_tokens = 0
    total_output_tokens = 0
    
    for task in tasks:
        desc = task["description"]
        decision = supervisor.classify(desc)
        result = router.execute(decision, desc)
        
        total_input_tokens += result.estimated_input_tokens
        total_output_tokens += result.estimated_output_tokens
        
        results.append({
            "input_tokens": result.estimated_input_tokens,
            "output_tokens": result.estimated_output_tokens
        })
        
    print(f"\nCompleted {len(tasks)} tasks")
    print("\nToken Usage Stats:")
    print(f"  total_input_tokens: {total_input_tokens}")
    print(f"  total_output_tokens: {total_output_tokens}")
        
    return results

if __name__ == "__main__":
    run_token_counter(os.path.join(os.path.dirname(__file__), "..", "benchmark", "tasks.json"))
