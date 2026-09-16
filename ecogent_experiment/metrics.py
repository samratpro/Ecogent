"""
Metrics and Cost Calculation.
"""

def generate_metrics_report(results: list[dict]) -> dict:
    """
    Generate a metrics report from a list of execution results.
    """
    total_tasks = len(results)
    cloud_calls = sum(r["cloud_calls"] for r in results)
    input_tokens = sum(r["input_tokens"] for r in results)
    output_tokens = sum(r["output_tokens"] for r in results)
    total_latency_ms = sum(r.get("latency_ms", 0.0) for r in results)
    
    local_executions = sum(1 for r in results if r.get("execution_path") == "local")
    cloud_executions = sum(1 for r in results if r.get("execution_path") == "cloud")
    
    return {
        "total_tasks": total_tasks,
        "local_executions": local_executions,
        "cloud_executions": cloud_executions,
        "total_cloud_calls": cloud_calls,
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "total_latency_ms": total_latency_ms,
        "average_latency_ms": total_latency_ms / total_tasks if total_tasks > 0 else 0
    }
