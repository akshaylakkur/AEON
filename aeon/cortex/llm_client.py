"""Unified LLM client with retries, cost tracking, and prompt caching.

Cost tracking uses a daily budget counter instead of wallet debits.
The agent has a research budget, not a survival balance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aeon.cortex.ollama_provider import OllamaProvider
from aeon.cortex.bedrock_provider import BedrockProvider
from aeon.cortex.tool_registry import LLMResponse, ToolCall, ToolRegistry

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Market hours definitions (UTC-based)
# ------------------------------------------------------------------ #

_MARKET_HOURS: dict[str, dict[str, Any]] = {
    "NYSE/NASDAQ": {
        "tz": "America/New_York",
        "open_hour": 9, "open_min": 30,
        "close_hour": 16, "close_min": 0,
        "weekdays": {0, 1, 2, 3, 4},  # Mon-Fri
    },
    "London (LSE)": {
        "tz": "Europe/London",
        "open_hour": 8, "open_min": 0,
        "close_hour": 16, "close_min": 30,
        "weekdays": {0, 1, 2, 3, 4},
    },
    "Tokyo (TSE)": {
        "tz": "Asia/Tokyo",
        "open_hour": 9, "open_min": 0,
        "close_hour": 15, "close_min": 0,
        "weekdays": {0, 1, 2, 3, 4},
    },
    "Crypto": {
        "tz": "UTC",
        "open_hour": 0, "open_min": 0,
        "close_hour": 23, "close_min": 59,
        "weekdays": {0, 1, 2, 3, 4, 5, 6},  # 24/7
    },
}


def _is_market_open(market_def: dict[str, Any], now_utc: datetime) -> bool:
    """Check if a market is currently open based on its local time."""
    tz = ZoneInfo(market_def["tz"])
    local = now_utc.astimezone(tz)
    if local.weekday() not in market_def["weekdays"]:
        return False
    open_time = local.replace(
        hour=market_def["open_hour"], minute=market_def["open_min"],
        second=0, microsecond=0,
    )
    close_time = local.replace(
        hour=market_def["close_hour"], minute=market_def["close_min"],
        second=0, microsecond=0,
    )
    return open_time <= local <= close_time


@dataclass(frozen=True, slots=True)
class ChatCost:
    """Cost breakdown for a chat operation."""

    estimated: float
    actual: float | None = None


class LLMClient:
    """Unified async interface over Ollama and Bedrock providers.

    Responsibilities:
    - Normalise the ``chat()`` API across providers.
    - Track inference costs against a daily budget (no wallet debits).
    - Retry transient failures with exponential backoff.
    - Cache prompt/response pairs to avoid redundant spend.
    - Execute tool calls and feed results back for multi-turn chains.
    - Provide context enrichment (time, market hours) for system prompts.
    """

    def __init__(
        self,
        provider: OllamaProvider | BedrockProvider,
        *,
        registry: ToolRegistry | None = None,
        cache_ttl: float = 300.0,
        max_retries: int = 3,
        base_backoff: float = 1.0,
        max_tool_turns: int = 10,
        daily_budget: float = 5.0,
    ) -> None:
        self._provider = provider
        self._registry = registry or ToolRegistry()
        self._cache_ttl = cache_ttl
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._max_tool_turns = max_tool_turns

        # Daily cost tracking
        self._daily_budget = daily_budget
        self._daily_cost: float = 0.0
        self._cost_date: date = date.today()
        self._total_cost: float = 0.0

        # In-memory prompt cache: key -> (LLMResponse, timestamp)
        self._cache: dict[str, tuple[LLMResponse, float]] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def is_budget_exceeded(self) -> bool:
        """Check if today's spend has exceeded the daily budget."""
        self._maybe_reset_daily_cost()
        return self._daily_cost >= self._daily_budget

    def get_cost_summary(self) -> dict[str, Any]:
        """Return today's spend, budget remaining, and total spend."""
        self._maybe_reset_daily_cost()
        return {
            "daily_cost": round(self._daily_cost, 6),
            "daily_budget": self._daily_budget,
            "budget_remaining": round(max(0.0, self._daily_budget - self._daily_cost), 6),
            "budget_exceeded": self.is_budget_exceeded(),
            "total_cost": round(self._total_cost, 6),
            "cost_date": self._cost_date.isoformat(),
        }

    def get_context_enrichment(self) -> str:
        """Return current time, date, day of week, and market hours status.

        This should be appended to every system prompt so the LLM has
        awareness of temporal context and which markets are active.
        """
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(ZoneInfo("America/New_York"))

        day_name = now_utc.strftime("%A")
        date_str = now_utc.strftime("%Y-%m-%d")
        time_utc_str = now_utc.strftime("%H:%M UTC")
        time_et_str = now_et.strftime("%H:%M ET")

        market_statuses: list[str] = []
        for name, defn in _MARKET_HOURS.items():
            status = "OPEN" if _is_market_open(defn, now_utc) else "CLOSED"
            market_statuses.append(f"  - {name}: {status}")

        return (
            f"\n--- Context ---\n"
            f"Date: {date_str} ({day_name})\n"
            f"Time: {time_utc_str} / {time_et_str}\n"
            f"Market hours:\n"
            + "\n".join(market_statuses)
            + "\n--- End Context ---"
        )

    async def chat(
        self,
        system_prompt: str | None,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        use_cache: bool = True,
        complexity_score: float = 0.5,
    ) -> tuple[LLMResponse, ChatCost]:
        """Send a chat request to the underlying provider.

        If *tools* is ``None`` and the client has a non-empty
        :class:`ToolRegistry`, the registry schemas are injected
        automatically.

        Args:
            system_prompt: Optional system-level instructions.
            messages: Conversation history (role/content dicts).
            tools: Explicit tool schemas.  If ``None``, registry schemas are used.
            use_cache: Whether to read from / write to the prompt cache.
            complexity_score: 0-1 score forwarded to cost estimation.

        Returns:
            ``(LLMResponse, ChatCost)`` tuple.

        Raises:
            LLMClientError: On unrecoverable provider failures or budget exceeded.
        """
        if tools is None and self._registry.list_tools():
            tools = self._provider_schemas()

        cache_key = _cache_key(self._provider.name, system_prompt, messages, tools)

        # Cache read
        if use_cache and cache_key in self._cache:
            cached_response, cached_at = self._cache[cache_key]
            if time.monotonic() - cached_at < self._cache_ttl:
                logger.debug("LLM cache hit")
                return cached_response, ChatCost(estimated=0.0, actual=0.0)
            del self._cache[cache_key]

        # Cost estimation and tracking
        cost = self._estimate_cost(messages, tools)
        self._maybe_reset_daily_cost()

        if self.is_budget_exceeded():
            logger.warning(
                "Daily LLM budget exceeded (spent %.4f of %.4f)",
                self._daily_cost,
                self._daily_budget,
            )
            raise LLMClientError(
                f"Daily budget exceeded: spent ${self._daily_cost:.4f} "
                f"of ${self._daily_budget:.4f}"
            )

        # Track cost internally (no wallet debit)
        self._daily_cost += cost
        self._total_cost += cost
        chat_cost = ChatCost(estimated=cost, actual=cost)

        # Provider call with retries
        try:
            response = await self._call_with_retries(
                system_prompt, messages, tools
            )
        except Exception as exc:
            logger.exception("LLM provider failure after retries")
            raise LLMClientError(f"Provider {self._provider.name} failed: {exc}") from exc

        # Cache write
        if use_cache:
            self._cache[cache_key] = (response, time.monotonic())

        return response, chat_cost

    async def chat_with_tools(
        self,
        system_prompt: str | None,
        messages: list[dict[str, Any]],
        *,
        auto_execute: bool = True,
        max_turns: int | None = None,
    ) -> tuple[LLMResponse, ChatCost, list[dict[str, Any]]]:
        """Multi-turn chat that handles tool calling automatically.

        The LLM is invoked.  If it requests tool calls they are executed
        (when *auto_execute* is ``True``) and the results are appended
        to the conversation.  This repeats until the LLM stops calling
        tools or *max_turns* is reached.

        Args:
            system_prompt: Optional system prompt.
            messages: Initial conversation history.
            auto_execute: Whether to execute requested tools automatically.
            max_turns: Override for the default ``max_tool_turns``.

        Returns:
            ``(final_response, total_cost, tool_results)`` where
            *tool_results* is a flat list of every tool execution result.
        """
        max_turns = max_turns or self._max_tool_turns
        conversation = list(messages)
        total_cost = 0.0
        all_results: list[dict[str, Any]] = []
        tool_schemas = self._provider_schemas()

        for turn in range(max_turns):
            response, cost = await self.chat(
                system_prompt=system_prompt,
                messages=conversation,
                tools=tool_schemas,
                use_cache=False,  # tool chains are rarely cacheable
            )
            total_cost += cost.actual or cost.estimated

            # Try native tool calls first, then fall back to text extraction
            tool_calls = list(response.tool_calls)

            if not tool_calls:
                # Bridge: extract tool calls from text JSON (for models that
                # don't support native tool calling protocol)
                tool_calls = self.extract_tool_calls_from_text(
                    response.thinking, self._registry
                )
                if tool_calls:
                    logger.debug(
                        "Extracted %d tool calls from text (turn %d/%d)",
                        len(tool_calls), turn + 1, max_turns,
                    )

            if not tool_calls:
                # No tool calls in any form -- reasoning complete
                return response, ChatCost(estimated=total_cost), all_results

            # Append assistant message
            conversation.append({
                "role": "assistant",
                "content": response.thinking,
            })

            if auto_execute and self._registry.list_tools():
                results = await self._registry.execute_all_async(tool_calls)
                all_results.extend(results)

                # Append tool results as structured user messages
                for result in results:
                    content = json.dumps({
                        "tool": result["tool_name"],
                        "result": result.get("result"),
                        "error": result.get("error"),
                    }, default=str)
                    conversation.append({"role": "user", "content": content})
            else:
                # No execution -- break so caller can handle tool calls
                return response, ChatCost(estimated=total_cost), all_results

        # Max turns reached
        return response, ChatCost(estimated=total_cost), all_results

    async def chat_with_tools_single_turn(
        self,
        system_prompt: str | None,
        conversation: list[dict[str, Any]],
    ) -> tuple[LLMResponse, ChatCost, list[dict[str, Any]], list[dict[str, Any]], bool]:
        """Single-turn LLM call with tool execution.

        Makes one LLM inference.  If the LLM requests tool calls, executes
        them, appends results to the conversation, and returns.  The caller
        controls the outer loop — deciding whether to continue, log, or
        switch subtasks between turns.

        Returns:
            ``(response, cost, tool_results, updated_conversation, done)``
            where *done* is ``True`` when the LLM produced a final text
            response without requesting any tools.
        """
        tool_schemas = self._provider_schemas()

        response, cost = await self.chat(
            system_prompt=system_prompt,
            messages=conversation,
            tools=tool_schemas,
            use_cache=False,
        )
        cost_value = cost.actual or cost.estimated

        tool_calls = list(response.tool_calls)
        if not tool_calls:
            tool_calls = self.extract_tool_calls_from_text(
                response.thinking, self._registry
            )

        if not tool_calls:
            return response, cost, [], conversation, True

        # Append assistant message with its thinking
        updated = list(conversation)
        updated.append({"role": "assistant", "content": response.thinking})

        # Execute the tool calls
        results = await self._registry.execute_all_async(tool_calls)

        for result in results:
            content = json.dumps({
                "tool": result["tool_name"],
                "result": result.get("result"),
                "error": result.get("error"),
            }, default=str)
            updated.append({"role": "user", "content": content})

        return response, cost, results, updated, False

    def clear_cache(self) -> None:
        """Evict all cached entries."""
        self._cache.clear()
        logger.debug("LLM prompt cache cleared")

    def cache_stats(self) -> dict[str, int]:
        """Return cache statistics."""
        return {"entries": len(self._cache)}

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _maybe_reset_daily_cost(self) -> None:
        """Reset the daily cost counter if the date has changed."""
        today = date.today()
        if today != self._cost_date:
            logger.info(
                "Daily cost reset: previous day spent $%.4f",
                self._daily_cost,
            )
            self._daily_cost = 0.0
            self._cost_date = today

    def _provider_schemas(self) -> list[dict[str, Any]]:
        """Return schemas in the format expected by the active provider."""
        if isinstance(self._provider, OllamaProvider):
            return self._registry.to_ollama_tools()
        return self._registry.to_bedrock_tools()

    def _estimate_cost(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> float:
        """Delegate cost estimation to the provider."""
        return self._provider.estimate_chat_cost(messages)

    async def _call_with_retries(
        self,
        system_prompt: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        """Call ``provider.chat`` with exponential-backoff retries."""
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                return await self._provider.chat(system_prompt, messages, tools)
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    backoff = self._base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s -- retrying in %.1fs",
                        attempt,
                        self._max_retries,
                        exc,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------ #
    # Text-based tool call extraction (fallback for models that don't  #
    # use native tool calling protocol)                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def extract_tool_calls_from_text(
        text: str, registry: ToolRegistry
    ) -> list[ToolCall]:
        """Parse text-based JSON actions embedded in LLM output.

        When a model doesn't use native tool calling but instead outputs
        JSON with an ``"actions"`` array, this extracts and validates
        those actions, converting them to :class:`ToolCall` objects.

        Handles markdown-fenced JSON, bare JSON objects, and embedded
        JSON within larger text blocks.

        Returns an empty list if no parseable actions are found.
        """
        parsed = _try_parse_json_stripped(text)
        if parsed is None:
            return []

        actions: list[dict[str, Any]] = []
        if isinstance(parsed, dict):
            actions = parsed.get("actions", [])
            if not isinstance(actions, list):
                actions = []
        elif isinstance(parsed, list):
            actions = [
                a for a in parsed
                if isinstance(a, dict) and "tool" in a
            ]

        tool_calls: list[ToolCall] = []
        registered = set(registry.list_tools())
        for action in actions:
            tool_name = action.get("tool", "")
            params = action.get("params", {})
            if not tool_name or not isinstance(params, dict):
                continue
            if tool_name not in registered:
                logger.debug(
                    "Skipping unknown tool '%s' from text extraction", tool_name
                )
                continue
            tool_calls.append(ToolCall(name=tool_name, arguments=params))

        return tool_calls


# ------------------------------------------------------------------ #
# Errors
# ------------------------------------------------------------------ #


class LLMClientError(Exception):
    """Raised when the LLM client encounters an unrecoverable failure."""


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _try_parse_json_stripped(text: str) -> dict[str, Any] | list[Any] | None:
    """Parse JSON from LLM output, stripping markdown fences."""
    stripped = text.strip()

    # Strip markdown code fences (e.g. ```json ... ```)
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    # Direct parse
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Try to find JSON embedded in text
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = stripped.find(start_char)
        end = stripped.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                continue

    return None


def _cache_key(
    provider_name: str,
    system_prompt: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> str:
    """Deterministic hash of the request for caching."""
    payload = {
        "provider": provider_name,
        "system": system_prompt,
        "messages": messages,
        "tools": tools,
    }
    json_bytes = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(json_bytes).hexdigest()
