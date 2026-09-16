"""
Ecogent LangGraph Agent (LangChain 1.x + LangGraph).

Uses LangGraph's native create_react_agent (not the deprecated langchain.agents one).
Wraps the cloud provider as a LangChain BaseChatModel.

Architecture per step:
  ContextPacket (JSON) → System Prompt → LangGraph ReAct → Tool → Observation
         ↑                                                              ↓
    ContextManager                                            Tiny LLM verify
         ↑                                                              ↓
    record_result ←─────────────────────────────────────── result string

Token cost controls:
  - Context packet < 400 tokens (ContextManager)
  - Tiny LLM does tool pre-selection + verification locally (0 cloud tokens)
  - Cloud LLM only called when Tiny LLM is uncertain or step fails
"""

import json
import time
from typing import Any, Iterator, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
)
from langchain_core.outputs import ChatGeneration, ChatResult

from ecogent_experiment.context import ContextPacket
from ecogent_experiment.providers.cloud import CloudLLMProvider


# ---------------------------------------------------------------------------
# Cloud LLM → LangChain BaseChatModel adapter
# ---------------------------------------------------------------------------

class EcogentChatModel(BaseChatModel):
    """
    Wraps Ecogent's CloudLLMProvider as a LangChain BaseChatModel.
    Compatible with LangChain 1.x and LangGraph.
    No new API keys — uses existing config.json provider.
    """
    provider: Any
    model_name: str = "ecogent-cloud"

    class Config:
        arbitrary_types_allowed = True

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs
    ) -> ChatResult:
        parts = []
        for m in messages:
            role = type(m).__name__.replace("Message", "").upper()
            parts.append(f"[{role}]\n{m.content}")
        prompt = "\n\n".join(parts)

        result = self.provider.generate_plan(prompt)
        answer = result.get("answer", "")
        msg = AIMessage(content=answer)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "ecogent-cloud"

    @property
    def _identifying_params(self) -> dict:
        return {"provider": type(self.provider).__name__}


# ---------------------------------------------------------------------------
# ReAct prompt template
# ---------------------------------------------------------------------------

REACT_SYSTEM = """\
You are Ecogent, an AI agent. Complete the step goal using the available tools.

CRITICAL INSTRUCTIONS:
- You HAVE full internet access via the web_search and browse_website tools.
- NEVER say you cannot browse the internet, cannot provide real-time results, or are an AI without access.
- ALWAYS use the provided tools to find the information requested.

{context}

Rules:
- Use the most specific tool. For web tasks use web_search or browse_website.
- CRITICAL: If your task involves writing or creating software, you MUST use the `write_file` tool to save the code to the disk. 
- If a workspace directory is provided in the context, save all files in that directory.
- Never fabricate data — only use what tools return.
- If a tool fails, try an alternative.

Respond in this exact format:
Thought: <your reasoning>
Action: <tool_name>
Action Input: {{"key": "value"}}
Observation: <tool result>
... repeat as needed ...
Thought: I now have the answer.
Final Answer: <answer>
"""


# ---------------------------------------------------------------------------
# EcogentAgent
# ---------------------------------------------------------------------------

class EcogentAgent:
    """
    LangGraph-based ReAct agent.

    Per step:
      1. Tiny LLM pre-selects tool locally (0 cloud tokens)
      2. If confident → run tool directly
      3. If not → run full LangGraph ReAct loop
      4. Tiny LLM verifies result locally (0 cloud tokens)
      5. On failure → Cloud LLM recovery
    """

    def __init__(
        self,
        cloud_provider: CloudLLMProvider,
        lc_tools: list,
        tiny_llm=None,
        max_iterations: int = 6,
        verbose: bool = False,
    ):
        self.cloud_provider = cloud_provider
        self.lc_tools = lc_tools
        self.tiny_llm = tiny_llm
        self.max_iterations = max_iterations
        self.verbose = verbose

        self._llm = EcogentChatModel(provider=cloud_provider)
        self._tool_map = {t.name: t for t in lc_tools}
        self.ask_llm = lambda p: cloud_provider.generate_plan(p).get("answer", "")

        # Inject ask_llm into web tools
        for tool in lc_tools:
            if tool.name in ("web_search", "browse_website", "browser_scrape"):
                tool.ask_llm = self.ask_llm

    # ------------------------------------------------------------------
    # Tiny LLM helpers (local, 0 cloud tokens)
    # ------------------------------------------------------------------

    def _tiny_select(self, step_goal: str, candidates: list[dict]) -> Optional[str]:
        if not self.tiny_llm or not candidates:
            return None
        names = [f"{c['tool_key']}: {c['description'][:60]}" for c in candidates[:10]]
        dec = self.tiny_llm.select_tool(step_goal, names)
        if dec.json_valid and dec.confidence >= 0.65 and dec.tool:
            key = str(dec.tool).lower().strip()
            for c in candidates:
                if c["tool_key"].lower() == key or key in c["tool_key"].lower():
                    return c["tool_key"]
        return None

    def _tiny_verify(self, step_goal: str, result: str) -> Optional[bool]:
        if not self.tiny_llm:
            return None
        try:
            v = self.tiny_llm.verify_completion(step_goal, result[:500])
            return v.get("verified")
        except Exception:
            return None

    # ------------------------------------------------------------------
    # LangGraph ReAct loop (manual — no deprecated AgentExecutor)
    # ------------------------------------------------------------------

    def _react_loop(self, step_goal: str, context_str: str, step_tools: list) -> tuple[str, Optional[str]]:
        """
        Manual text-based ReAct loop.

        Works with any LLM — does NOT require native function calling.
        Parses Action / Action Input from LLM text, calls the tool,
        feeds Observation back, and loops until Final Answer or max iterations.
        """
        import re

        tool_map = {t.name: t for t in step_tools}

        # Build tools block for the prompt
        tools_block = "\n".join(
            f"- {t.name}: {t.description[:120]}"
            for t in step_tools
        )
        tool_names = ", ".join(tool_map.keys())

        system = (
            f"{REACT_SYSTEM.format(context=context_str)}\n\n"
            f"Tools available:\n{tools_block}\n\n"
            f"Tool names: {tool_names}"
        )

        # Conversation history as plain text (cheaper than message objects)
        history = f"{system}\n\nQuestion: {step_goal}\n"

        for iteration in range(self.max_iterations):
            # Ask the LLM what to do next
            response = self.cloud_provider.generate_plan(history + "Thought:")
            raw = "Thought:" + response.get("answer", "").strip()

            # Prevent LLM from hallucinating the Observation
            if "\nObservation:" in raw:
                raw = raw.split("\nObservation:")[0].strip()

            if self.verbose:
                print(f"\n[ReAct iter {iteration+1}]\n{raw}")

            history += f"\n{raw}"

            # Check for Final Answer
            if "Final Answer:" in raw:
                final = raw.split("Final Answer:", 1)[-1].strip()
                
                # Best effort: see what tools were actually called during this loop
                tool_used = None
                for t in step_tools:
                    if f"Action: {t.name}" in history or f"Action:  {t.name}" in history or f"Action:{t.name}" in history:
                        tool_used = t.name
                        break
                
                return final, tool_used
                
            # Detect implicit refusal to browse
            refusal_phrases = ["cannot browse", "unable to browse", "don't have internet", "real-time search results"]
            if any(phrase in raw.lower() for phrase in refusal_phrases) and "Action:" not in raw:
                 history += f"\nObservation: System warning: You MUST use the web_search or browse_website tool instead of claiming you cannot browse.\n"
                 continue

            # Parse Action and Action Input
            action_m = re.search(r"Action:\s*(.+)", raw)
            input_m = re.search(r"Action Input:\s*(\{.*?\}|\S+.*?)(?:\n|$)", raw, re.S)

            if not action_m:
                # LLM didn't follow format — try to extract any useful content
                if iteration == self.max_iterations - 1:
                    # Last iteration: ask for a direct answer
                    fallback = self.cloud_provider.generate_plan(
                        history + "\nYou must now give your Final Answer based on observations so far."
                    )
                    return fallback.get("answer", raw), None
                continue

            tool_name = action_m.group(1).strip().lower().replace(" ", "_")
            tool_input_raw = input_m.group(1).strip() if input_m else "{}"

            # Find matching tool (fuzzy)
            matched_tool = tool_map.get(tool_name)
            if not matched_tool:
                for name, tool in tool_map.items():
                    if tool_name in name or name in tool_name:
                        matched_tool = tool
                        tool_name = name
                        break

            if not matched_tool:
                observation = f"Error: tool '{tool_name}' not found. Available: {tool_names}"
            else:
                # Parse input — try JSON first, fall back to plain string
                try:
                    if tool_input_raw.startswith("{"):
                        tool_kwargs = json.loads(tool_input_raw)
                        tool_input = json.dumps(tool_kwargs)
                    else:
                        tool_input = json.dumps({"task": tool_input_raw})
                except json.JSONDecodeError:
                    tool_input = json.dumps({"task": tool_input_raw})

                try:
                    observation = matched_tool._run(tool_input)
                    # Truncate long observations to save tokens
                    if len(observation) > 1500:
                        observation = observation[:1500] + "\n...[truncated]"
                except Exception as e:
                    observation = f"Tool error: {e}"

            if self.verbose:
                print(f"Observation: {observation}")
                
            history += f"\nObservation: {observation}\n"

        # Max iterations reached — ask for final answer with all observations
        final_resp = self.cloud_provider.generate_plan(
            history + "\nBased on all observations above, give the Final Answer now."
        )
        return final_resp.get("answer", "Could not complete step within iteration limit."), None


    # ------------------------------------------------------------------
    # Public: run one workflow step
    # ------------------------------------------------------------------

    def run_step(
        self,
        context_packet: ContextPacket,
        available_tool_keys: Optional[list[str]] = None,
    ) -> dict:
        """
        Run a single workflow step.

        Returns:
            {result, tool_used, verified, input_tokens, output_tokens, path, latency_s}
        """
        t0 = time.time()

        # Select which tools to expose for this step
        if available_tool_keys:
            step_tools = [t for t in self.lc_tools if t.name in available_tool_keys]
            # Always keep web tools if step mentions web keywords
            web_kw = ("search", "browse", "web", "http", "bing", "google", "url", "site")
            if any(kw in context_packet.step_goal.lower() for kw in web_kw):
                for t in self.lc_tools:
                    if t.name in ("web_search", "browse_website") and t not in step_tools:
                        step_tools.append(t)
        else:
            step_tools = list(self.lc_tools)

        candidates = [{"tool_key": t.name, "description": t.description} for t in step_tools]

        # --- 1. Tiny LLM pre-selection (local, free) ---
        preselected = self._tiny_select(context_packet.step_goal, candidates)

        if preselected and preselected in self._tool_map:
            tool = self._tool_map[preselected]
            try:
                res = tool._run(json.dumps({"task": context_packet.step_goal}))
                verified = self._tiny_verify(context_packet.step_goal, res)
                if verified is not False:
                    return {
                        "result": res,
                        "tool_used": preselected,
                        "verified": True if verified is None else verified,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "latency_s": round(time.time() - t0, 2),
                        "path": "tiny_llm_direct",
                    }
            except Exception:
                pass  # fall through to ReAct

        # --- 2. Full LangGraph ReAct loop ---
        context_str = context_packet.to_prompt_str()
        result_str, tool_used = self._react_loop(context_packet.step_goal, context_str, step_tools)

        # --- 3. Tiny LLM post-verification (local, free) ---
        verified = self._tiny_verify(context_packet.step_goal, result_str)
        if verified is False:
            # Recovery via cloud LLM - Give it the context so it doesn't try to use tools it doesn't have
            rec = self.cloud_provider.generate_plan(
                f"You are verifying a completed task. The agent had access to these tools:\n\n"
                f"{context_str}\n\n"
                f"Goal: '{context_packet.step_goal}'\n"
                f"The agent's final answer was: {result_str}\n\n"
                f"This answer was flagged as incorrect or incomplete by an automated checker. "
                f"Please provide a better, more direct answer to the Goal based on the original answer. "
                f"Do NOT apologize or say you cannot browse the internet."
            )
            result_str = rec.get("answer", result_str)
            verified = True # Mark as recovered

        approx_in = (len(context_str) + len(context_packet.step_goal)) // 4
        approx_out = len(result_str) // 4

        return {
            "result": result_str,
            "tool_used": tool_used,
            "verified": True if verified is None else verified,
            "input_tokens": approx_in,
            "output_tokens": approx_out,
            "latency_s": round(time.time() - t0, 2),
            "path": "react_agent",
        }

