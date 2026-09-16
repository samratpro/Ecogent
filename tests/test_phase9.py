"""
Phase 9 Tests: Metrics and Results.
"""

from ecogent_experiment.metrics import calculate_cost, generate_metrics_report
from ecogent_experiment.comparison import compare_results

class TestMetrics:
    def test_calculate_cost(self):
        # 1M input ($1.00) + 1M output ($5.00) = $6.00
        cost = calculate_cost(1_000_000, 1_000_000)
        assert cost == 6.00
        
    def test_generate_metrics_report(self):
        results = [
            {"execution_path": "local", "cloud_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 10},
            {"execution_path": "cloud", "cloud_calls": 1, "input_tokens": 1000, "output_tokens": 500, "latency_ms": 1000}
        ]
        
        metrics = generate_metrics_report(results)
        
        assert metrics["total_tasks"] == 2
        assert metrics["local_executions"] == 1
        assert metrics["cloud_executions"] == 1
        assert metrics["total_cloud_calls"] == 1
        assert metrics["total_input_tokens"] == 1000
        assert metrics["total_output_tokens"] == 500
        # $1 / 1M * 1000 = $0.001
        # $5 / 1M * 500 = $0.0025
        # Total: $0.0035
        assert abs(metrics["total_cost_usd"] - 0.0035) < 1e-6
        assert metrics["total_latency_ms"] == 1010
        
class TestComparison:
    def test_compare_results(self):
        ecogent = [
            {"execution_path": "local", "cloud_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 10},
            {"execution_path": "cloud", "cloud_calls": 1, "input_tokens": 1000, "output_tokens": 500, "latency_ms": 1000}
        ]
        baseline = [
            {"execution_path": "cloud", "cloud_calls": 1, "input_tokens": 100, "output_tokens": 50, "latency_ms": 200},
            {"execution_path": "cloud", "cloud_calls": 1, "input_tokens": 1000, "output_tokens": 500, "latency_ms": 1000}
        ]
        
        comp = compare_results(ecogent, baseline)
        
        assert comp["cloud_calls_saved"] == 1
        # Baseline cost: 1100 input ($0.0011), 550 output ($0.00275) = $0.00385
        # Ecogent cost: 1000 input ($0.001), 500 output ($0.0025) = $0.0035
        # Savings: $0.00035
        assert abs(comp["cost_savings_usd"] - 0.00035) < 1e-6
