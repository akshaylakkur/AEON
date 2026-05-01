"""Research executor for AEON -- executes research tool call chains based on LLM decisions.

Replaces the old TacticalExecutor (trade/product execution) with a research-focused
executor that runs tool call sequences and iterative deep dives.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aeon.cortex.llm_client import LLMClient
from aeon.cortex.llm_reasoning import LLMReasoner, LLMReasoningError
from aeon.cortex.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class ResearchExecutor:
    """Executes research tool call chains based on LLM decisions.

    The executor takes a research plan (from :class:`ResearchPriorityEngine`)
    and orchestrates the actual tool calls needed to gather data, then
    feeds results back to the LLM for synthesis.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        reasoner: LLMReasoner,
        *,
        max_tool_calls_per_plan: int = 20,
        max_deep_dive_iterations: int = 5,
    ) -> None:
        self._client = llm_client
        self._reasoner = reasoner
        self._max_tool_calls = max_tool_calls_per_plan
        self._max_deep_dive_iterations = max_deep_dive_iterations
        self._execution_history: list[dict[str, Any]] = []

    async def execute_research_plan(
        self,
        plan: dict[str, Any],
        tool_registry: ToolRegistry,
    ) -> list[dict[str, Any]]:
        """Execute a series of tool calls as part of a research plan.

        Uses the LLM's tool-calling loop to gather data for the given
        research topic. The LLM decides which tools to call and in what
        order.

        Args:
            plan: A research plan item dict with ``topic``, ``approach``,
                ``tools``, and ``research_questions`` keys.
            tool_registry: Registry of available research tools.

        Returns:
            List of finding dicts, each with ``source``, ``data``,
            ``summary``, and ``timestamp`` keys.
        """
        topic = plan.get("topic", "unknown")
        approach = plan.get("approach", "general research")
        questions = plan.get("research_questions", [])
        tools_hint = plan.get("tools", [])

        tool_summary = tool_registry.get_tool_summary()

        system_prompt = (
            "You are an AI hedge fund research manager executing a research plan. "
            "Use the available tools to gather data and answer the research questions. "
            "Be thorough but efficient -- call the most relevant tools first. "
            "After gathering data, synthesize your findings.\n\n"
            f"{tool_summary}"
        )

        user_message = (
            f"## Research Topic\n{topic}\n\n"
            f"## Approach\n{approach}\n\n"
        )
        if questions:
            user_message += "## Questions to Answer\n"
            for q in questions:
                user_message += f"- {q}\n"
        if tools_hint:
            user_message += f"\n## Suggested Tools\n{', '.join(tools_hint)}\n"

        user_message += (
            "\nGather data using the available tools, then summarize your "
            "findings. Call tools to get real data before drawing conclusions."
        )

        try:
            response, cost, tool_results = await self._client.chat_with_tools(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                auto_execute=True,
                max_turns=min(self._max_tool_calls, 10),
            )
        except Exception as exc:
            logger.error("Research execution failed for topic '%s': %s", topic, exc)
            return [{
                "source": "error",
                "data": {"error": str(exc)},
                "summary": f"Research execution failed: {exc}",
                "topic": topic,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]

        # Build findings from tool results and LLM synthesis
        findings: list[dict[str, Any]] = []

        for result in tool_results:
            findings.append({
                "source": result.get("tool_name", "unknown"),
                "data": result.get("result"),
                "error": result.get("error"),
                "topic": topic,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # Add the LLM's synthesis as a finding
        if response.thinking.strip():
            findings.append({
                "source": "llm_synthesis",
                "data": {"analysis": response.thinking.strip()},
                "summary": response.thinking.strip()[:500],
                "topic": topic,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        self._execution_history.append({
            "topic": topic,
            "tool_calls": len(tool_results),
            "findings": len(findings),
            "cost": cost.actual or cost.estimated,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return findings

    async def deep_dive(
        self,
        topic: str,
        initial_data: dict[str, Any],
        tool_registry: ToolRegistry,
    ) -> dict[str, Any]:
        """Perform iterative deep research on a topic using multiple tool calls.

        The LLM examines initial data, identifies gaps, and iteratively
        calls tools to fill those gaps until it has enough information
        for a thorough analysis.

        Args:
            topic: The research topic for the deep dive.
            initial_data: Data already gathered on this topic.
            tool_registry: Registry of available tools.

        Returns:
            A dict with ``topic``, ``analysis``, ``evidence``, ``gaps``,
            ``confidence``, and ``iterations`` keys.
        """
        tool_summary = tool_registry.get_tool_summary()
        all_evidence: list[dict[str, Any]] = []

        if initial_data:
            all_evidence.append({
                "source": "initial_data",
                "data": initial_data,
            })

        analysis = ""
        gaps: list[str] = []

        for iteration in range(self._max_deep_dive_iterations):
            # Ask the LLM what gaps remain and what tools to call
            evidence_text = "\n".join(
                f"- [{e.get('source', 'unknown')}]: "
                f"{str(e.get('data', ''))[:300]}"
                for e in all_evidence
            )

            system_prompt = (
                "You are performing a deep-dive research investigation. "
                "Examine the evidence gathered so far, identify gaps, and "
                "either call more tools to fill those gaps or provide your "
                "final analysis if you have enough information.\n\n"
                f"{tool_summary}"
            )

            user_message = (
                f"## Deep Dive: {topic}\n\n"
                f"## Evidence So Far (iteration {iteration + 1})\n"
                f"{evidence_text}\n\n"
                "Identify gaps in the evidence and call tools to fill them, "
                "OR if you have sufficient evidence, provide your final analysis "
                "without calling any tools."
            )

            try:
                response, cost, tool_results = await self._client.chat_with_tools(
                    system_prompt=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    auto_execute=True,
                    max_turns=3,
                )
            except Exception as exc:
                logger.error(
                    "Deep dive iteration %d failed for '%s': %s",
                    iteration + 1, topic, exc,
                )
                break

            # Collect new evidence from tool results
            for result in tool_results:
                all_evidence.append({
                    "source": result.get("tool_name", "unknown"),
                    "data": result.get("result"),
                    "iteration": iteration + 1,
                })

            # If no tools were called, the LLM is done
            if not tool_results:
                analysis = response.thinking.strip()
                break

            analysis = response.thinking.strip()

        # Final synthesis if we ran out of iterations
        if not analysis:
            try:
                synth_result = await self._reasoner.research_reasoning(
                    task=f"Provide a final analysis of '{topic}' based on all evidence gathered.",
                    context={"topic": topic, "iterations": self._max_deep_dive_iterations},
                    evidence=all_evidence,
                )
                analysis = synth_result.text
            except LLMReasoningError as exc:
                analysis = f"Deep dive incomplete due to reasoning failure: {exc}"

        return {
            "topic": topic,
            "analysis": analysis,
            "evidence": all_evidence,
            "gaps": gaps,
            "confidence": 0.5,  # LLM can refine this in the analysis text
            "iterations": min(iteration + 1, self._max_deep_dive_iterations),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_execution_history(self) -> list[dict[str, Any]]:
        """Return the history of research executions."""
        return list(self._execution_history)
