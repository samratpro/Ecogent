"""
Phase 8 Tests: Benchmarks.
"""

import os
import json
import pytest
import tempfile
from ecogent_experiment.benchmark import run_benchmark
from ecogent_experiment.benchmark_baseline import run_baseline

class TestBenchmarks:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tasks_file = os.path.join(self.tmpdir, "tasks.json")
        tasks = [
            {"id": "t1", "description": "Read the file doc.txt"}
        ]
        with open(self.tasks_file, "w") as f:
            json.dump(tasks, f)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ecogent_benchmark(self):
        results = run_benchmark(self.tasks_file)
        assert len(results) == 1
        assert results[0]["id"] == "t1"
        # "Read the file doc.txt" is simple enough to hit rules and go local
        assert results[0]["execution_path"] == "local"
        assert results[0]["cloud_calls"] == 0

    def test_baseline_benchmark(self):
        results = run_baseline(self.tasks_file)
        assert len(results) == 1
        assert results[0]["id"] == "t1"
        # Baseline always goes to cloud
        assert results[0]["cloud_calls"] == 1
        assert results[0]["input_tokens"] > 0
