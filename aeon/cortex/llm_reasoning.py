"""Shared LLM reasoning utility for the AEON Hedge Fund Research Manager.

Provides a common async interface for any subsystem to call the LLM
with a structured context prompt and get back either free-form natural
language reasoning or a parsed JSON-structured response.

No silent rule-based fallbacks -- if the LLM is unreachable, the caller
gets an exception or an explicit empty/error result, never a hardcoded
"smart" response pretending to be LLM reasoning.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from aeon.core.reasoning_log import get_reasoning_log
from aeon.cortex.llm_client import LLMClient

logger = logging.getLogger(__name__)


class LLMReasoningError(Exception):
    """Raised when LLM reasoning fails and no fallback is appropriate."""


@dataclass
class ReasoningResult:
    """Outcome of an LLM reasoning call."""

    text: str
    structured: dict[str, Any] | None = None
    cost: float = 0.0
    model: str = ""


class LLMReasoner:
    """Async interface for subsystems to reason through the LLM.

    Usage::

        reasoner = LLMReasoner(llm_client)
        result = await reasoner.reason(
            task="evaluate this opportunity",
            context={"market": "crypto", "recent_news": [...]},
        )
        print(result.text)  # natural language reasoning
    """

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        source_tag: str = "llm_reasoner",
        max_json_retries: int = 2,
    ) -> None:
        self._client = llm_client
        self._source_tag = source_tag
        self._max_json_retries = max_json_retries
        self._log = get_reasoning_log()

    @property
    def client(self) -> LLMClient:
        return self._client

    # ------------------------------------------------------------------ #
    # Public API -- Core reasoning methods
    # ------------------------------------------------------------------ #

    async def reason(
        self,
        task: str,
        context: dict[str, Any],
        *,
        system_hint: str | None = None,
    ) -> ReasoningResult:
        """Ask the LLM to reason about *task* given *context*.

        Returns a :class:`ReasoningResult` with the LLM's natural language
        thinking.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        prompt = self._build_prompt(task, context)
        system = self._build_system_prompt(system_hint)

        try:
            response, cost = await self._client.chat(
                system_prompt=system,
                messages=[{"role": "user", "content": prompt}],
                use_cache=False,
            )
        except Exception as exc:
            self._log.append(
                f"LLM reasoning failed for task '{task}': {exc}",
                source=self._source_tag,
            )
            raise LLMReasoningError(f"LLM reasoning failed: {exc}") from exc

        text = response.thinking.strip()
        self._log.append(text, source=self._source_tag)

        return ReasoningResult(
            text=text,
            cost=cost.actual or cost.estimated,
            model=self._client.provider_name,
        )

    async def reason_structured(
        self,
        task: str,
        context: dict[str, Any],
        *,
        output_schema: dict[str, Any] | None = None,
        system_hint: str | None = None,
    ) -> ReasoningResult:
        """Ask the LLM to reason and return a JSON-structured response.

        The LLM is prompted to return a JSON object matching *output_schema*.
        If the first response isn't valid JSON, up to *max_json_retries*
        additional attempts are made with correction hints.

        Returns a :class:`ReasoningResult` where ``structured`` contains the
        parsed dict and ``text`` contains the raw LLM output.

        Raises:
            LLMReasoningError: If the LLM call fails or JSON cannot be
                parsed after retries.
        """
        schema_instruction = ""
        if output_schema:
            schema_instruction = (
                f"\n\nReturn ONLY a JSON object matching this schema:\n"
                f"```json\n{json.dumps(output_schema, indent=2)}\n```"
            )

        prompt = self._build_prompt(task, context) + schema_instruction
        system = self._build_system_prompt(system_hint)

        last_text = ""
        total_cost = 0.0

        for attempt in range(self._max_json_retries + 1):
            try:
                response, cost = await self._client.chat(
                    system_prompt=system,
                    messages=[{"role": "user", "content": prompt}],
                    use_cache=False,
                )
            except Exception as exc:
                self._log.append(
                    f"LLM structured reasoning failed for task '{task}': {exc}",
                    source=self._source_tag,
                )
                raise LLMReasoningError(
                    f"LLM reasoning failed: {exc}"
                ) from exc

            text = response.thinking.strip()
            total_cost += cost.actual or cost.estimated
            last_text = text

            parsed = _try_parse_json(text)
            if parsed is not None:
                self._log.append(
                    f"Structured reasoning completed for '{task}'",
                    source=self._source_tag,
                )
                return ReasoningResult(
                    text=text,
                    structured=parsed,
                    cost=total_cost,
                    model=self._client.provider_name,
                )

            # Retry with correction hint
            prompt = (
                f"Your previous response was not valid JSON. "
                f"Please return ONLY a JSON object, no markdown fences.\n\n"
                f"Previous response:\n{text[:500]}"
            )
            logger.warning(
                "LLM structured reasoning attempt %d returned non-JSON, retrying.",
                attempt + 1,
            )

        self._log.append(
            f"LLM structured reasoning failed to produce valid JSON for '{task}'",
            source=self._source_tag,
        )
        raise LLMReasoningError(
            f"LLM reasoning returned non-JSON after {self._max_json_retries + 1} attempts"
        )

    async def reason_list(
        self,
        task: str,
        context: dict[str, Any],
        *,
        item_schema: dict[str, Any] | None = None,
        system_hint: str | None = None,
    ) -> ReasoningResult:
        """Ask the LLM to produce a JSON list of items.

        Convenience wrapper around :meth:`reason_structured` that expects
        the LLM to return a JSON array. Returns a :class:`ReasoningResult`
        where ``structured`` is the parsed list.
        """
        schema = {
            "type": "array",
            "items": item_schema or {},
        }
        result = await self.reason_structured(
            task=task,
            context=context,
            output_schema=schema,
            system_hint=system_hint,
        )

        if isinstance(result.structured, list):
            return result

        # If the LLM wrapped the list in an object, try to extract it
        if isinstance(result.structured, dict):
            for value in result.structured.values():
                if isinstance(value, list):
                    result = ReasoningResult(
                        text=result.text,
                        structured=value,
                        cost=result.cost,
                        model=result.model,
                    )
                    return result

        raise LLMReasoningError(
            f"LLM reasoning did not return a JSON list for task '{task}'"
        )

    # ------------------------------------------------------------------ #
    # Public API -- Research-specific reasoning methods
    # ------------------------------------------------------------------ #

    async def research_reasoning(
        self,
        task: str,
        context: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> ReasoningResult:
        """Specialized reasoning for investment research synthesis.

        The LLM receives a research task, contextual information, and
        evidence gathered from tools, then synthesizes a coherent analysis.

        Args:
            task: Description of the research task.
            context: Background context (market state, user guidance, etc.).
            evidence: List of evidence dicts gathered from tools. Each
                should have at least ``source`` and ``data`` keys.

        Returns:
            A :class:`ReasoningResult` with synthesized analysis.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        evidence_text = ""
        if evidence:
            evidence_parts: list[str] = ["## Evidence"]
            for i, item in enumerate(evidence, 1):
                source = item.get("source", "unknown")
                data = item.get("data", item)
                evidence_parts.append(
                    f"### Evidence {i} (source: {source})\n"
                    f"{json.dumps(data, indent=2, default=str)}"
                )
            evidence_text = "\n".join(evidence_parts)

        prompt = self._build_prompt(task, context)
        if evidence_text:
            prompt += f"\n\n{evidence_text}"

        prompt += (
            "\n\n## Instructions\n"
            "Synthesize the evidence above into a coherent analysis. "
            "Identify patterns, contradictions, and gaps in the evidence. "
            "Be explicit about your confidence level and what additional "
            "information would strengthen the analysis."
        )

        system = self._build_system_prompt(
            "You are an expert investment research analyst. Synthesize "
            "evidence into actionable insights. Be rigorous, cite specific "
            "evidence, and clearly distinguish facts from interpretation."
        )

        try:
            response, cost = await self._client.chat(
                system_prompt=system,
                messages=[{"role": "user", "content": prompt}],
                use_cache=False,
            )
        except Exception as exc:
            self._log.append(
                f"Research reasoning failed for task '{task}': {exc}",
                source=self._source_tag,
            )
            raise LLMReasoningError(
                f"Research reasoning failed: {exc}"
            ) from exc

        text = response.thinking.strip()
        self._log.append(text, source=f"{self._source_tag}:research")

        return ReasoningResult(
            text=text,
            cost=cost.actual or cost.estimated,
            model=self._client.provider_name,
        )

    async def generate_recommendation(
        self,
        asset: str,
        evidence: list[dict[str, Any]],
        user_guidance: str = "",
    ) -> ReasoningResult:
        """Generate a structured investment recommendation.

        The LLM receives evidence about a specific asset and produces
        a structured recommendation with thesis, risks, and action items.

        Args:
            asset: The asset or topic being recommended on.
            evidence: List of evidence dicts supporting the recommendation.
            user_guidance: Optional user preferences or constraints.

        Returns:
            A :class:`ReasoningResult` where ``structured`` contains
            the recommendation dict with keys like ``action``, ``thesis``,
            ``confidence``, ``risks``, ``timeframe``, ``key_metrics``.

        Raises:
            LLMReasoningError: If the LLM call fails or output is unparseable.
        """
        evidence_summary: list[str] = []
        for item in evidence:
            source = item.get("source", "unknown")
            data = item.get("data", item)
            if isinstance(data, dict):
                data_str = json.dumps(data, indent=2, default=str)
            else:
                data_str = str(data)
            evidence_summary.append(f"[{source}]: {data_str}")

        context: dict[str, Any] = {
            "asset": asset,
            "evidence_count": len(evidence),
        }
        if user_guidance:
            context["user_guidance"] = user_guidance

        task = (
            f"Generate an investment recommendation for '{asset}' based on "
            f"the evidence below.\n\n"
            f"Evidence:\n" + "\n---\n".join(evidence_summary)
        )

        output_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "BUY, SELL, HOLD, or WATCH",
                },
                "thesis": {
                    "type": "string",
                    "description": "2-4 sentence investment thesis",
                },
                "confidence": {
                    "type": "number",
                    "description": "0.0 to 1.0 confidence in the recommendation",
                },
                "risks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key risks that could invalidate the thesis",
                },
                "catalysts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Upcoming events or factors that could move the price",
                },
                "timeframe": {
                    "type": "string",
                    "description": "Recommended holding period (e.g. '1-2 weeks', '3-6 months')",
                },
                "key_metrics": {
                    "type": "object",
                    "description": "Relevant metrics supporting the thesis",
                },
                "evidence_quality": {
                    "type": "string",
                    "description": "Assessment of evidence quality: strong, moderate, or weak",
                },
            },
            "required": ["action", "thesis", "confidence", "risks", "timeframe"],
        }

        system_hint = (
            "You are an expert investment research analyst generating a "
            "recommendation. Be honest about uncertainty. If the evidence "
            "is insufficient, say so and recommend WATCH rather than forcing "
            "a buy/sell. Always consider what could go wrong."
        )

        result = await self.reason_structured(
            task=task,
            context=context,
            output_schema=output_schema,
            system_hint=system_hint,
        )

        # Log the recommendation
        if result.structured:
            self._log.log_recommendation_reasoning(
                topic=asset,
                thesis=result.structured.get("thesis", ""),
                confidence=result.structured.get("confidence", 0.0),
                evidence=[e.get("source", "unknown") for e in evidence],
            )

        return result

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_prompt(task: str, context: dict[str, Any]) -> str:
        """Build a user message from a task description and context dict."""
        parts = [f"## Task\n{task}"]
        if context:
            parts.append("## Context")
            for key, value in context.items():
                parts.append(f"- **{key}**: {value}")
        return "\n".join(parts)

    def _build_system_prompt(self, custom_hint: str | None = None) -> str:
        """Build a system prompt with context enrichment appended."""
        base = custom_hint or self._default_system_prompt()
        context_enrichment = self._client.get_context_enrichment()
        return f"{base}\n{context_enrichment}"

    @staticmethod
    def _default_system_prompt() -> str:
        return (
            "You are AEON, an AI hedge fund research manager. Your role is to "
            "research financial markets, analyze data, and produce investment "
            "recommendations. Reason step by step. Be concise but thorough. "
            "Consider risks, catalysts, and evidence quality. "
            "Produce natural language reasoning that reflects genuine deliberation."
        )


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _try_parse_json(text: str) -> dict[str, Any] | list[Any] | None:
    """Attempt to extract and parse JSON from an LLM response."""
    stripped = text.strip()

    # Strip markdown code fences
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    # Direct parse
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return parsed
        except json.JSONDecodeError:
            pass

    # Try to find JSON embedded in text
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = stripped.find(start_char)
        end = stripped.rfind(end_char)
        if start != -1 and end > start:
            try:
                parsed = json.loads(stripped[start : end + 1])
                if isinstance(parsed, (dict, list)):
                    return parsed
            except json.JSONDecodeError:
                continue

    return None
