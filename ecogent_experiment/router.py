"""
Execution Router.

Takes a SupervisorDecision and routes to the appropriate execution path:
- Direct local tool execution
- Tiny LLM fallback for verification
- Cloud escalation

Tracks routing statistics per path.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ecogent_experiment.supervisor import SupervisorDecision


@dataclass
class ExecutionResult:
    """Result of executing a task through the router."""
    success: bool = False
    output: Any = None
    error: str = ""
    execution_path: str = ""  # "local", "tiny_llm", "cloud"
    tool_used: Optional[str] = None
    agent_used: Optional[str] = None
    cloud_calls: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    latency_ms: float = 0.0
    verified: bool = False
    verification_source: str = ""  # "assertion", "tiny_llm", "cloud"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": str(self.output)[:500] if self.output else None,
            "error": self.error,
            "execution_path": self.execution_path,
            "tool_used": self.tool_used,
            "agent_used": self.agent_used,
            "cloud_calls": self.cloud_calls,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "latency_ms": round(self.latency_ms, 2),
            "verified": self.verified,
            "verification_source": self.verification_source,
        }


@dataclass
class RouterStats:
    """Accumulated routing statistics."""
    total_routed: int = 0
    local_executions: int = 0
    tiny_llm_executions: int = 0
    cloud_executions: int = 0
    successful: int = 0
    failed: int = 0
    total_cloud_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "total_routed": self.total_routed,
            "local_executions": self.local_executions,
            "tiny_llm_executions": self.tiny_llm_executions,
            "cloud_executions": self.cloud_executions,
            "successful": self.successful,
            "failed": self.failed,
            "total_cloud_calls": self.total_cloud_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }


class Router:
    """
    Execution router that dispatches tasks based on supervisor decisions.

    Routes to:
    1. Local tool execution (no LLM)
    2. Local tool + Tiny LLM verification
    3. Cloud LLM for complex tasks
    """

    def __init__(self, tool_executor=None, tiny_llm=None, cloud_provider=None):
        """
        Initialize the router.

        Args:
            tool_executor: Callable(tool_name, **kwargs) -> result
            tiny_llm: TinyLLM instance for verification
            cloud_provider: CloudLLMProvider for escalation
        """
        self.tool_executor = tool_executor
        self.tiny_llm = tiny_llm
        self.cloud_provider = cloud_provider
        self.stats = RouterStats()

    def execute(
        self,
        decision: SupervisorDecision,
        task: str,
        tool_kwargs: Optional[dict] = None,
    ) -> ExecutionResult:
        """
        Execute a task based on the supervisor's decision.

        Args:
            decision: SupervisorDecision from the supervisor.
            task: Original task description.
            tool_kwargs: Optional keyword arguments for the tool.

        Returns:
            ExecutionResult with execution details.
        """
        self.stats.total_routed += 1

        if decision.execution == "local" and decision.tool:
            result = self._execute_local(decision, task, tool_kwargs or {})
        elif decision.execution == "cloud" or decision.escalate:
            result = self._execute_cloud(decision, task)
        else:
            # Fallback: try local, then cloud
            result = self._execute_local(decision, task, tool_kwargs or {})
            if not result.success and self.cloud_provider:
                result = self._execute_cloud(decision, task)

        # Update stats
        if result.success:
            self.stats.successful += 1
        else:
            self.stats.failed += 1

        self.stats.total_cloud_calls += result.cloud_calls
        self.stats.total_input_tokens += result.estimated_input_tokens
        self.stats.total_output_tokens += result.estimated_output_tokens

        return result

    def _execute_local(
        self,
        decision: SupervisorDecision,
        task: str,
        tool_kwargs: dict,
    ) -> ExecutionResult:
        """Execute a task locally using a registered tool."""
        self.stats.local_executions += 1

        result = ExecutionResult(
            execution_path="local",
            tool_used=decision.tool,
            agent_used=decision.agent,
        )

        if not self.tool_executor:
            result.success = False
            result.error = "No tool executor configured"
            return result

        if not decision.tool:
            result.success = False
            result.error = "No tool specified for local execution"
            return result

        try:
            import time
            start = time.perf_counter()
            output = self.tool_executor(decision.tool, **tool_kwargs)
            result.latency_ms = (time.perf_counter() - start) * 1000
            result.output = output
            result.success = True

            # Optionally verify with Tiny LLM
            if self.tiny_llm:
                verification = self.tiny_llm.verify_completion(
                    task, str(output)[:500]
                )
                result.verified = verification.get("verified", False)
                result.verification_source = "tiny_llm"
            else:
                result.verified = True
                result.verification_source = "none"

        except Exception as e:
            result.success = False
            result.error = str(e)

        return result

    def _execute_cloud(
        self,
        decision: SupervisorDecision,
        task: str,
    ) -> ExecutionResult:
        """Escalate a task to the cloud LLM."""
        self.stats.cloud_executions += 1

        result = ExecutionResult(
            execution_path="cloud",
            tool_used=decision.tool,
            agent_used=decision.agent,
        )

        if not self.cloud_provider:
            result.success = False
            result.error = "No cloud provider configured"
            return result

        try:
            import time
            start = time.perf_counter()
            cloud_result = self.cloud_provider.generate_plan(task)
            result.latency_ms = (time.perf_counter() - start) * 1000
            result.output = cloud_result
            result.success = True
            result.cloud_calls = 1
            result.estimated_input_tokens = cloud_result.get(
                "input_tokens", 0
            )
            result.estimated_output_tokens = cloud_result.get(
                "output_tokens", 0
            )
            result.verified = True
            result.verification_source = "cloud"

        except Exception as e:
            result.success = False
            result.error = str(e)

        return result

    def get_stats(self) -> dict:
        """Get accumulated routing statistics."""
        return self.stats.to_dict()
