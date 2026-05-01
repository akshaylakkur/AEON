"""Dynamic tool registry for Project ÆON.

Tools are discovered via the ``@register_tool`` decorator and expose
name, description, and parameter schema so the LLM can budget and route.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger("aeon.tools")


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    parameters: tuple[ToolParameter, ...]
    cost_estimate: float = 0.0
    async_callable: bool = False
    category: str = "general"


def _parse_docstring_args(func: Callable[..., Any]) -> dict[str, str]:
    """Parse the ``Args:`` section of a function's docstring.

    Returns a mapping from parameter name to its description string.
    """
    doc = inspect.getdoc(func) or ""
    result: dict[str, str] = {}

    # Find the Args: section
    args_match = re.search(r"^\s*Args:\s*$", doc, re.MULTILINE)
    if not args_match:
        return result

    # Get text after "Args:"
    rest = doc[args_match.end():]

    # Stop at the next top-level section (Returns:, Raises:, etc.) or end
    section_end = re.search(r"^\s*\w[\w ]*:\s*$", rest, re.MULTILINE)
    if section_end:
        rest = rest[:section_end.start()]

    # Parse each argument line:  "  param_name: description" or "  param_name (type): description"
    current_name = None
    current_desc_parts: list[str] = []

    for line in rest.split("\n"):
        # Match "  param_name: description" or "  param_name (type): description"
        arg_match = re.match(r"^\s{4,}(\w+)(?:\s*\([^)]*\))?\s*:\s*(.+)?", line)
        if arg_match:
            # Save previous param
            if current_name is not None:
                result[current_name] = " ".join(current_desc_parts).strip()
            current_name = arg_match.group(1)
            desc = (arg_match.group(2) or "").strip()
            current_desc_parts = [desc] if desc else []
        elif current_name is not None and line.strip():
            # Continuation line
            current_desc_parts.append(line.strip())
        elif not line.strip() and current_name is not None:
            # Blank line ends current param
            result[current_name] = " ".join(current_desc_parts).strip()
            current_name = None
            current_desc_parts = []

    # Don't forget the last param
    if current_name is not None:
        result[current_name] = " ".join(current_desc_parts).strip()

    return result


@dataclass
class ToolRegistry:
    """Central registry for all discoverable tools."""

    _tools: dict[str, Callable[..., Any]] = field(default_factory=dict)
    _info: dict[str, ToolInfo] = field(default_factory=dict)

    def register(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        cost_estimate: float = 0.0,
        category: str = "general",
    ) -> Callable[..., Any]:
        """Decorator that registers a function as a tool.

        Parameter schemas are inferred from type hints and defaults.
        Parameter descriptions are extracted from docstring ``Args:`` sections.
        """

        def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__
            tool_desc = description or (func.__doc__ or "").strip().split("\n")[0]

            # Parse docstring for parameter descriptions
            arg_docs = _parse_docstring_args(func)

            sig = inspect.signature(func)
            params: list[ToolParameter] = []
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "cls"):
                    continue
                param_type = "string"
                if param.annotation is not inspect.Parameter.empty:
                    ann = param.annotation
                    ann_str = str(ann)
                    if ann is int or ann_str == "int":
                        param_type = "integer"
                    elif ann is float or ann_str == "float":
                        param_type = "number"
                    elif ann is bool or ann_str == "bool":
                        param_type = "boolean"
                    elif ann in (list, set, tuple) or ann_str.startswith("list[") or ann_str in ("list", "set", "tuple"):
                        param_type = "array"
                    elif ann is dict or ann_str.startswith("dict[") or ann_str == "dict":
                        param_type = "object"
                is_required = param.default is inspect.Parameter.empty
                param_desc = arg_docs.get(param_name, "")
                params.append(
                    ToolParameter(
                        name=param_name,
                        type=param_type,
                        description=param_desc,
                        required=is_required,
                        default=param.default if not is_required else None,
                    )
                )

            is_async = asyncio.iscoroutinefunction(func)
            self._tools[tool_name] = func
            self._info[tool_name] = ToolInfo(
                name=tool_name,
                description=tool_desc,
                parameters=tuple(params),
                cost_estimate=cost_estimate,
                async_callable=is_async,
                category=category,
            )
            logger.debug("Registered tool: %s (async=%s, category=%s)", tool_name, is_async, category)
            return func

        if fn is None:
            return _decorator
        return _decorator(fn)

    def get(self, name: str) -> Callable[..., Any] | None:
        return self._tools.get(name)

    def get_info(self, name: str) -> ToolInfo | None:
        return self._info.get(name)

    def list_tools(self) -> list[str]:
        return list(self._info.keys())

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    async def call(self, name: str, **kwargs: Any) -> Any:
        """Call a registered tool by name with the given kwargs."""
        fn = self._tools.get(name)
        if fn is None:
            raise ValueError(f"Tool '{name}' not found in registry")
        if asyncio.iscoroutinefunction(fn):
            return await fn(**kwargs)
        return fn(**kwargs)


# Global singleton registry
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def register_tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    cost_estimate: float = 0.0,
    category: str = "general",
) -> Callable[..., Any]:
    """Convenience decorator using the global registry."""
    return get_registry().register(
        fn, name=name, description=description, cost_estimate=cost_estimate, category=category,
    )


def export_to_cortex_registry(cortex_registry: Any) -> None:
    """Copy all globally registered tools into the cortex :class:`ToolRegistry`.

    Preserves parameter descriptions, types, and defaults from the global
    registry so the LLM sees accurate tool schemas.
    """
    from aeon.cortex.tool_registry import ToolDefinition

    global_registry = get_registry()
    for info_name in global_registry.list_tools():
        fn = global_registry.get(info_name)
        info = global_registry.get_info(info_name)
        if fn is None:
            continue
        # Build JSON schema from parameters, preserving descriptions
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in info.parameters:
            prop: dict[str, Any] = {"type": p.type}
            if p.description:
                prop["description"] = p.description
            if p.required:
                required.append(p.name)
            if p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        cortex_registry.register(
            ToolDefinition(
                name=info.name,
                description=info.description,
                parameters=schema,
                handler=fn,
                category=info.category,
            )
        )
