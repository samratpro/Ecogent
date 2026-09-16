"""
GGUF inference engine.

Wraps llama-cli subprocess for local model inference.
Measures latency and resource consumption.
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

import psutil


@dataclass
class InferenceResult:
    """Result of a local inference call."""
    output: str
    latency_ms: float
    process_rss_mb: float = 0.0
    model_path: str = ""
    tokens_generated: int = 0
    success: bool = True
    error: str = ""


@dataclass
class InferenceStats:
    """Accumulated inference statistics."""
    total_calls: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    peak_rss_mb: float = 0.0
    json_valid_count: int = 0
    json_invalid_count: int = 0

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    @property
    def json_validity_rate(self) -> float:
        total = self.json_valid_count + self.json_invalid_count
        if total == 0:
            return 0.0
        return self.json_valid_count / total

    def to_dict(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_tokens": self.total_tokens,
            "peak_rss_mb": round(self.peak_rss_mb, 2),
            "json_validity_rate": round(self.json_validity_rate, 4),
        }


class InferenceEngine:
    """
    Local GGUF inference engine using llama-cli subprocess.

    This engine does NOT execute any model-generated commands.
    It only captures the model's text output for structured decision-making.
    """

    def __init__(
        self,
        runtime_path: str,
        model_path: str,
        context_size: int = 512,
        temperature: float = 0.1,
        max_tokens: int = 256,
        top_p: float = 0.9,
        repeat_penalty: float = 1.1,
    ):
        """
        Initialize the inference engine.

        Args:
            runtime_path: Path to llama-cli binary.
            model_path: Path to GGUF model file.
            context_size: Context window size.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            top_p: Top-p sampling parameter.
            repeat_penalty: Repetition penalty.
        """
        self.runtime_path = os.path.abspath(runtime_path)
        self.model_path = os.path.abspath(model_path)
        self.context_size = context_size
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.repeat_penalty = repeat_penalty
        self.stats = InferenceStats()

    def verify(self) -> bool:
        """Check that runtime and model files exist."""
        if not os.path.exists(self.runtime_path):
            return False
        if not os.path.exists(self.model_path):
            return False
        return True

    def infer(self, prompt: str, max_tokens: Optional[int] = None) -> InferenceResult:
        """
        Run inference on the local model.

        Args:
            prompt: The prompt to send to the model.
            max_tokens: Override max tokens for this call.

        Returns:
            InferenceResult with output and metrics.
        """
        if not self.verify():
            return InferenceResult(
                output="",
                latency_ms=0.0,
                success=False,
                error=f"Runtime or model not found. Runtime: {self.runtime_path}, Model: {self.model_path}",
            )

        tokens = max_tokens or self.max_tokens

        cmd = [
            self.runtime_path,
            "-m", self.model_path,
            "-p", prompt,
            "-n", str(tokens),
            "-st",  # Single-turn mode to prevent hanging
            "--temp", str(self.temperature),
            "--top-p", str(self.top_p),
            "--repeat-penalty", str(self.repeat_penalty),
            "--ctx-size", str(self.context_size),
            "--no-display-prompt",
            "--log-disable",
        ]

        start_time = time.perf_counter()
        rss_mb = 0.0

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Try to measure RSS while process is running
            try:
                ps_proc = psutil.Process(process.pid)
                # Give it a moment to load the model
                time.sleep(0.5)
                if process.poll() is None:  # still running
                    mem_info = ps_proc.memory_info()
                    rss_mb = mem_info.rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            stdout, stderr = process.communicate(timeout=180)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if process.returncode != 0:
                return InferenceResult(
                    output="",
                    latency_ms=elapsed_ms,
                    process_rss_mb=rss_mb,
                    model_path=self.model_path,
                    success=False,
                    error=f"Process exited with code {process.returncode}: {stderr[:500]}",
                )

            output = stdout.strip()

            # Estimate token count (rough: ~4 chars per token)
            est_tokens = max(1, len(output) // 4)

            # Update stats
            self.stats.total_calls += 1
            self.stats.total_latency_ms += elapsed_ms
            self.stats.total_tokens += est_tokens
            self.stats.peak_rss_mb = max(self.stats.peak_rss_mb, rss_mb)

            return InferenceResult(
                output=output,
                latency_ms=elapsed_ms,
                process_rss_mb=rss_mb,
                model_path=self.model_path,
                tokens_generated=est_tokens,
                success=True,
            )

        except subprocess.TimeoutExpired:
            process.kill()
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return InferenceResult(
                output="",
                latency_ms=elapsed_ms,
                success=False,
                error="Inference timed out (>180s)",
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return InferenceResult(
                output="",
                latency_ms=elapsed_ms,
                success=False,
                error=str(e),
            )

    def get_model_info(self) -> dict:
        """Get model file information."""
        info = {
            "runtime": self.runtime_path,
            "model": self.model_path,
            "context_size": self.context_size,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if os.path.exists(self.model_path):
            info["model_size_mb"] = round(
                os.path.getsize(self.model_path) / (1024 * 1024), 2
            )
        return info


def create_engine_from_config(config_path: str) -> InferenceEngine:
    """
    Create an InferenceEngine from config.json.

    Args:
        config_path: Path to config.json file.

    Returns:
        Configured InferenceEngine instance.
    """
    config_dir = os.path.dirname(os.path.abspath(config_path))
    root_dir = os.path.dirname(config_dir)

    with open(config_path) as f:
        config = json.load(f)

    runtime_cfg = config["llm_runtime"]
    model_cfg = config["model"]

    # Resolve paths relative to project root
    runtime_path = os.path.join(root_dir, runtime_cfg["path"])
    model_path = os.path.join(root_dir, model_cfg["path"])

    # On Windows, add .exe if not present
    if os.name == "nt" and not runtime_path.endswith(".exe"):
        runtime_path += ".exe"

    return InferenceEngine(
        runtime_path=runtime_path,
        model_path=model_path,
        context_size=model_cfg.get("context_size", 512),
        temperature=model_cfg.get("temperature", 0.1),
        max_tokens=model_cfg.get("max_tokens", 256),
        top_p=model_cfg.get("top_p", 0.9),
        repeat_penalty=model_cfg.get("repeat_penalty", 1.1),
    )
