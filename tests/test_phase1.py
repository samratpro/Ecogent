"""
Phase 1 Tests: CLI, Inference Engine, JSON Parser, Tiny LLM.
"""

import json
import os
import pytest

from ecogent_experiment.parser import extract_json, validate_decision, _fix_json_string


# ============================================================
# JSON Parser Tests
# ============================================================


class TestExtractJson:
    """Test JSON extraction from various model output formats."""

    def test_clean_json(self):
        """Pure JSON string should parse directly."""
        text = '{"intent": "file_operation", "complexity": "simple"}'
        result = extract_json(text)
        assert result is not None
        assert result["intent"] == "file_operation"

    def test_json_with_markdown_fence(self):
        """JSON inside markdown code fences."""
        text = """Here is my response:
```json
{"intent": "file_operation", "complexity": "simple", "tool": "rename_file"}
```
That's my classification."""
        result = extract_json(text)
        assert result is not None
        assert result["tool"] == "rename_file"

    def test_json_with_surrounding_text(self):
        """JSON embedded in natural language."""
        text = 'The classification is {"intent": "data_processing", "complexity": "moderate"} based on analysis.'
        result = extract_json(text)
        assert result is not None
        assert result["intent"] == "data_processing"

    def test_json_with_trailing_comma(self):
        """JSON with trailing comma (common model error)."""
        text = '{"intent": "file_operation", "tool": "rename_file",}'
        result = extract_json(text)
        assert result is not None
        assert result["intent"] == "file_operation"

    def test_empty_input(self):
        """Empty string should return None."""
        assert extract_json("") is None
        assert extract_json("   ") is None
        assert extract_json(None) is None

    def test_no_json(self):
        """Text without JSON should return None."""
        result = extract_json("This is just plain text with no JSON at all.")
        assert result is None

    def test_nested_json(self):
        """Nested JSON objects should be handled."""
        text = '{"intent": "complex", "params": {"file": "test.csv", "action": "read"}}'
        result = extract_json(text)
        assert result is not None
        assert result["intent"] == "complex"
        assert result["params"]["file"] == "test.csv"

    def test_json_with_code_fence_no_lang(self):
        """JSON in code fence without language specifier."""
        text = """```
{"intent": "system_info"}
```"""
        result = extract_json(text)
        assert result is not None
        assert result["intent"] == "system_info"


class TestValidateDecision:
    """Test decision validation and normalization."""

    def test_complete_decision(self):
        """A complete decision should pass through."""
        data = {
            "intent": "file_operation",
            "complexity": "simple",
            "tool": "rename_file",
            "execution": "local",
            "escalate": False,
            "confidence": 0.95,
        }
        result = validate_decision(data)
        assert result["intent"] == "file_operation"
        assert result["complexity"] == "simple"
        assert result["tool"] == "rename_file"
        assert result["execution"] == "local"
        assert result["escalate"] is False
        assert result["confidence"] == 0.95

    def test_missing_fields_get_defaults(self):
        """Missing fields should get sensible defaults."""
        result = validate_decision({})
        assert result["intent"] == "unknown"
        assert result["complexity"] == "unknown"
        assert result["tool"] is None
        assert result["execution"] == "cloud"
        assert result["escalate"] is True
        assert result["confidence"] == 0.0

    def test_invalid_complexity_normalized(self):
        """Invalid complexity should become 'unknown'."""
        result = validate_decision({"complexity": "very_hard"})
        assert result["complexity"] == "unknown"

    def test_invalid_execution_normalized(self):
        """Invalid execution should become 'cloud'."""
        result = validate_decision({"execution": "hybrid"})
        assert result["execution"] == "cloud"

    def test_confidence_clamped(self):
        """Confidence should be clamped to [0, 1]."""
        result = validate_decision({"confidence": 1.5})
        assert result["confidence"] == 1.0

        result = validate_decision({"confidence": -0.5})
        assert result["confidence"] == 0.0

    def test_confidence_from_string(self):
        """String confidence should be converted to float."""
        result = validate_decision({"confidence": "0.85"})
        assert result["confidence"] == 0.85


class TestFixJsonString:
    """Test JSON fix heuristics."""

    def test_trailing_comma(self):
        fixed = _fix_json_string('{"a": 1, "b": 2,}')
        result = json.loads(fixed)
        assert result == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self):
        fixed = _fix_json_string('{"a": [1, 2,]}')
        result = json.loads(fixed)
        assert result == {"a": [1, 2]}


# ============================================================
# Inference Engine Tests (unit tests with mock)
# ============================================================


class TestInferenceEngine:
    """Test InferenceEngine without requiring actual model."""

    def test_verify_missing_files(self):
        """Should fail verification if files don't exist."""
        from ecogent_experiment.inference import InferenceEngine

        engine = InferenceEngine(
            runtime_path="/nonexistent/llama-cli",
            model_path="/nonexistent/model.gguf",
        )
        assert engine.verify() is False

    def test_infer_without_files(self):
        """Should return error result if files are missing."""
        from ecogent_experiment.inference import InferenceEngine

        engine = InferenceEngine(
            runtime_path="/nonexistent/llama-cli",
            model_path="/nonexistent/model.gguf",
        )
        result = engine.infer("test prompt")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_model_info(self):
        """Should return model metadata dict."""
        from ecogent_experiment.inference import InferenceEngine

        engine = InferenceEngine(
            runtime_path="/some/llama-cli",
            model_path="/some/model.gguf",
            context_size=256,
            temperature=0.2,
        )
        info = engine.get_model_info()
        assert info["context_size"] == 256
        assert info["temperature"] == 0.2

    def test_stats_initial(self):
        """Stats should start at zero."""
        from ecogent_experiment.inference import InferenceStats

        stats = InferenceStats()
        assert stats.total_calls == 0
        assert stats.avg_latency_ms == 0.0
        assert stats.json_validity_rate == 0.0

    def test_stats_computation(self):
        """Stats should compute correctly."""
        from ecogent_experiment.inference import InferenceStats

        stats = InferenceStats(
            total_calls=10,
            total_latency_ms=5000.0,
            json_valid_count=8,
            json_invalid_count=2,
        )
        assert stats.avg_latency_ms == 500.0
        assert stats.json_validity_rate == 0.8


# ============================================================
# Tiny LLM Tests (unit tests with mock)
# ============================================================


class TestTinyLLMDecision:
    """Test TinyLLMDecision data class."""

    def test_default_values(self):
        from ecogent_experiment.tiny_llm import TinyLLMDecision

        decision = TinyLLMDecision()
        assert decision.intent == "unknown"
        assert decision.escalate is True
        assert decision.json_valid is False

    def test_to_dict(self):
        from ecogent_experiment.tiny_llm import TinyLLMDecision

        decision = TinyLLMDecision(
            intent="file_operation",
            complexity="simple",
            tool="rename_file",
            execution="local",
            escalate=False,
            confidence=0.95,
            json_valid=True,
            latency_ms=150.5,
        )
        d = decision.to_dict()
        assert d["intent"] == "file_operation"
        assert d["confidence"] == 0.95
        assert d["latency_ms"] == 150.5


# ============================================================
# CLI Tests
# ============================================================


class TestCLI:
    """Test CLI command registration."""

    def test_cli_group_exists(self):
        from ecogent_experiment.cli import cli
        assert cli is not None

    def test_cli_has_commands(self):
        from ecogent_experiment.cli import cli
        assert "system-info" in cli.commands
        assert "infer" in cli.commands
        assert "inspect-tool" in cli.commands
        assert "inspect-workflow" in cli.commands
        assert "benchmark" in cli.commands
