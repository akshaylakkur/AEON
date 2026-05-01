"""Ollama LLM provider — implements both cortex and metamind interfaces."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import Any

import httpx

from aeon.cortex.model_router import AbstractLLMProvider
from aeon.cortex.tool_registry import LLMResponse, ToolCall
from aeon.metamind.code_generator import LLMProvider

logger = logging.getLogger(__name__)


class OllamaProvider(AbstractLLMProvider, LLMProvider):
    """Concrete LLM provider backed by a local Ollama server.

    Implements both the async cortex interface (``AbstractLLMProvider``)
    and the sync metamind interface (``LLMProvider``) so a single instance
    can be wired into the ModelRouter *and* the SelfModificationEngine.

    Adds ``chat()`` with native tool-calling support via Ollama's
    ``/api/chat`` endpoint.
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout: float = 120.0,
    ) -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    # ------------------------------------------------------------------
    # AbstractLLMProvider (async cortex interface)
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return f"ollama/{self._model}"

    async def infer(self, prompt: str, **kwargs: Any) -> str:
        """Run async inference against Ollama ``/api/generate``."""
        url = f"{self._host}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            **kwargs,
        }
        logger.debug("Ollama infer: model=%s prompt_len=%d", self._model, len(prompt))
        resp = await self._http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")

    def estimate_cost(self, prompt: str, **kwargs: Any) -> float:
        """Ollama runs locally — cost is always zero."""
        return 0.0

    def estimate_chat_cost(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> float:
        """Ollama runs locally — cost is always zero."""
        return 0.0

    # ------------------------------------------------------------------
    # Tool-calling chat interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        system_prompt: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Run a chat completion with optional tool calling.

        Args:
            system_prompt: Optional system prompt.
            messages: List of message dicts ``{"role": "user|assistant", "content": "..."}``.
            tools: List of Ollama-style tool schemas (from :meth:`ToolRegistry.to_ollama_tools`).

        Returns:
            :class:`LLMResponse` with thinking text and any tool calls.
        """
        url = f"{self._host}/api/chat"
        ollama_messages = list(messages)
        if system_prompt:
            ollama_messages.insert(0, {"role": "system", "content": system_prompt})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ollama_messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        logger.debug(
            "Ollama chat: model=%s messages=%d tools=%d",
            self._model,
            len(ollama_messages),
            len(tools) if tools else 0,
        )
        resp = await self._http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        message = data.get("message", {})
        thinking = message.get("content", "") or ""

        raw_tool_calls = message.get("tool_calls", [])
        tool_calls: list[ToolCall] = []
        for raw in raw_tool_calls:
            func = raw.get("function", {})
            name = func.get("name", "")
            if not name:
                continue
            args = func.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            elif not isinstance(args, dict):
                args = {}
            tool_calls.append(ToolCall(name=name, arguments=args or {}))

        return LLMResponse(thinking=thinking, tool_calls=tool_calls)

    # ------------------------------------------------------------------
    # LLMProvider (sync metamind interface)
    # ------------------------------------------------------------------

    def complete(self, prompt: str) -> str:
        """Synchronous completion via stdlib urllib (thread-safe, no event loop)."""
        url = f"{self._host}/api/generate"
        payload = json.dumps({
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        logger.debug("Ollama complete: model=%s prompt_len=%d", self._model, len(prompt))
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read())
        return data.get("response", "")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._http.aclose()

    async def health_check(self) -> bool:
        """Return True if the Ollama server is reachable and the model is loaded."""
        try:
            resp = await self._http.get(f"{self._host}/api/tags", timeout=5.0)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            return any(m.get("name", "").startswith(self._model) for m in models)
        except Exception:
            return False
