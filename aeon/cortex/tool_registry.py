"""Tool registry for LLM tool-calling bridge."""

from __future__ import annotations

import functools
import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A single tool call requested by an LLM."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Structured response from an LLM chat with tool-calling support."""

    thinking: str
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Definition of a tool callable by an LLM."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    category: str = "general"  # "research", "market_data", "communication", "memory", "analysis"


class ToolRegistry:
    """Registry of tools that can be discovered and executed by LLMs.

    Tools are stored in Anthropic ``tool_use`` format and transformed
    to provider-specific schemas at call time.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def register(self, tool: ToolDefinition) -> None:
        """Register a :class:`ToolDefinition`."""
        if tool.name in self._tools:
            logger.warning("Overwriting existing tool: %s", tool.name)
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def tool(
        self,
        name: str | None = None,
        description: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Callable:
        """Decorator to auto-register a function as a tool.

        Usage::

            registry = ToolRegistry()

            @registry.tool(name="get_price", description="Get market price", params={...})
            def get_price(symbol: str) -> float:
                ...
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__
            tool_desc = description or (func.__doc__ or "").strip()
            tool_params = params or _infer_params_from_signature(func)
            self.register(
                ToolDefinition(
                    name=tool_name,
                    description=tool_desc,
                    parameters=tool_params,
                    handler=func,
                )
            )
            return func

        return decorator

    # ------------------------------------------------------------------ #
    # Schema access
    # ------------------------------------------------------------------ #

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return tool schemas in Anthropic ``tool_use`` format.

        Each entry is::

            {"name": ..., "description": ..., "input_schema": <parameters>}
        """
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in self._tools.values()
        ]

    def to_ollama_tools(self) -> list[dict[str, Any]]:
        """Return schemas in Ollama/OpenAI ``tools`` format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def to_bedrock_tools(self) -> list[dict[str, Any]]:
        """Return schemas in Bedrock ``converse`` ``toolConfig`` format."""
        return [
            {
                "toolSpec": {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": {"json": t.parameters},
                }
            }
            for t in self._tools.values()
        ]

    def list_tools(self) -> list[str]:
        """Return a list of registered tool names."""
        return list(self._tools.keys())

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Retrieve a single tool definition by name."""
        return self._tools.get(name)

    def get_tools_by_category(self, category: str) -> list[ToolDefinition]:
        """Return all tools belonging to the given category.

        Args:
            category: Category label (e.g. ``"research"``, ``"market_data"``).

        Returns:
            A list of matching :class:`ToolDefinition` objects.
        """
        return [t for t in self._tools.values() if t.category == category]

    def get_tool_summary(self) -> str:
        """Return a natural language summary of all available tools grouped by category.

        Includes parameter names, types, whether required/optional, and default
        values so the LLM knows exactly what arguments each tool accepts.

        Useful for including in LLM system prompts so the model knows what
        tools are available and how to use them.
        """
        by_category: dict[str, list[ToolDefinition]] = {}
        for t in self._tools.values():
            by_category.setdefault(t.category, []).append(t)

        if not by_category:
            return "No tools are currently registered."

        parts: list[str] = ["# Available Tools\n"]
        for category in sorted(by_category.keys()):
            tools = by_category[category]
            parts.append(f"## {category.replace('_', ' ').title()}")
            for t in sorted(tools, key=lambda x: x.name):
                # Build parameter summary
                param_parts: list[str] = []
                props = t.parameters.get("properties", {})
                required_params = set(t.parameters.get("required", []))
                for pname, pschema in props.items():
                    ptype = pschema.get("type", "any")
                    is_req = pname in required_params
                    default = pschema.get("default")
                    pdesc = pschema.get("description", "")

                    parts_for_param = [f"{pname} ({ptype}"]
                    if is_req:
                        parts_for_param.append(", required)")
                    elif default is not None:
                        parts_for_param.append(f", optional, default={default!r})")
                    else:
                        parts_for_param.append(", optional)")

                    if pdesc:
                        parts_for_param.append(f" -- {pdesc}")

                    param_parts.append("".join(parts_for_param))

                if param_parts:
                    params_str = "Params: " + "; ".join(param_parts)
                else:
                    params_str = "Params: none"

                parts.append(f"- **{t.name}**: {t.description} {params_str}")
            parts.append("")  # blank line between categories

        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        """Validate *arguments* against the tool schema and invoke its handler.

        Returns the raw handler result.  Validation errors are raised as
        :class:`ToolValidationError`.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ToolExecutionError(f"Tool '{name}' is not registered")

        _validate_arguments(arguments, tool.parameters, name)

        sig = inspect.signature(tool.handler)
        try:
            sig.bind(**arguments)
        except TypeError as exc:
            raise ToolValidationError(
                f"Arguments for '{name}' do not match handler signature: {exc}"
            ) from exc

        try:
            if inspect.iscoroutinefunction(tool.handler):
                raise ToolExecutionError(
                    f"Tool '{name}' is async — use execute_async instead"
                )
            result = tool.handler(**arguments)
            logger.debug("Tool '%s' executed successfully", name)
            return result
        except (ToolValidationError, ToolExecutionError):
            raise
        except Exception as exc:
            raise ToolExecutionError(
                f"Tool '{name}' handler raised {type(exc).__name__}: {exc}"
            ) from exc

    async def call(self, name: str, **kwargs: Any) -> Any:
        """Call a tool by name with keyword arguments.

        Compatible with the global :class:`~aeon.tools.registry.ToolRegistry`
        interface so that the :class:`~aeon.tools.tool_verifier.ToolVerifier`
        can work with either registry type.
        """
        return await self.execute_async(name, kwargs)

    async def execute_async(self, name: str, arguments: dict[str, Any]) -> Any:
        """Async variant of :meth:`execute`."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolExecutionError(f"Tool '{name}' is not registered")

        _validate_arguments(arguments, tool.parameters, name)

        sig = inspect.signature(tool.handler)
        try:
            sig.bind(**arguments)
        except TypeError as exc:
            raise ToolValidationError(
                f"Arguments for '{name}' do not match handler signature: {exc}"
            ) from exc

        try:
            if inspect.iscoroutinefunction(tool.handler):
                result = await tool.handler(**arguments)
            else:
                result = tool.handler(**arguments)
            logger.debug("Tool '%s' executed successfully (async)", name)
            return result
        except (ToolValidationError, ToolExecutionError):
            raise
        except Exception as exc:
            raise ToolExecutionError(
                f"Tool '{name}' handler raised {type(exc).__name__}: {exc}"
            ) from exc

    def execute_all(self, tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
        """Execute a batch of :class:`ToolCall` objects synchronously.

        Returns a list of result dicts with keys ``tool_name``, ``result``,
        and optionally ``error``.
        """
        results: list[dict[str, Any]] = []
        for tc in tool_calls:
            try:
                result = self.execute(tc.name, tc.arguments)
                results.append({"tool_name": tc.name, "result": result})
            except Exception as exc:
                results.append(
                    {"tool_name": tc.name, "result": None, "error": str(exc)}
                )
        return results

    async def execute_all_async(
        self, tool_calls: list[ToolCall]
    ) -> list[dict[str, Any]]:
        """Async variant of :meth:`execute_all`."""
        results: list[dict[str, Any]] = []
        for tc in tool_calls:
            try:
                result = await self.execute_async(tc.name, tc.arguments)
                results.append({"tool_name": tc.name, "result": result})
            except Exception as exc:
                results.append(
                    {"tool_name": tc.name, "result": None, "error": str(exc)}
                )
        return results


# ------------------------------------------------------------------ #
# Errors
# ------------------------------------------------------------------ #


class ToolValidationError(Exception):
    """Raised when tool arguments fail schema or signature validation."""


class ToolExecutionError(Exception):
    """Raised when a tool handler fails at runtime."""


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


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

    current_name = None
    current_desc_parts: list[str] = []

    for line in rest.split("\n"):
        arg_match = re.match(r"^\s{4,}(\w+)(?:\s*\([^)]*\))?\s*:\s*(.+)?", line)
        if arg_match:
            if current_name is not None:
                result[current_name] = " ".join(current_desc_parts).strip()
            current_name = arg_match.group(1)
            desc = (arg_match.group(2) or "").strip()
            current_desc_parts = [desc] if desc else []
        elif current_name is not None and line.strip():
            current_desc_parts.append(line.strip())
        elif not line.strip() and current_name is not None:
            result[current_name] = " ".join(current_desc_parts).strip()
            current_name = None
            current_desc_parts = []

    if current_name is not None:
        result[current_name] = " ".join(current_desc_parts).strip()

    return result


def _infer_params_from_signature(func: Callable[..., Any]) -> dict[str, Any]:
    """Build a minimal JSON Schema 'object' from *func*'s signature.

    Extracts parameter descriptions from the function's docstring ``Args:``
    section and includes default values in the schema.
    """
    sig = inspect.signature(func)
    arg_docs = _parse_docstring_args(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        param_schema: dict[str, Any] = {}
        ann = param.annotation
        if ann is not inspect.Parameter.empty:
            param_schema.update(_py_type_to_json_schema(ann))
        else:
            param_schema["type"] = "string"

        # Add description from docstring
        desc = arg_docs.get(param_name, "")
        if desc:
            param_schema["description"] = desc

        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            # Add default value to schema when it is JSON-serializable
            if param.default is not None:
                param_schema["default"] = param.default

        properties[param_name] = param_schema
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _py_type_to_json_schema(annotation: Any) -> dict[str, Any]:
    """Best-effort mapping of Python types to JSON Schema types.

    Handles both real types and string annotations from
    ``from __future__ import annotations``.
    """
    ann_str = str(annotation)
    origin = getattr(annotation, "__origin__", None)
    if origin is list or annotation is list or ann_str in ("list",) or ann_str.startswith("list["):
        return {"type": "array"}
    if origin is dict or annotation is dict or ann_str in ("dict",) or ann_str.startswith("dict["):
        return {"type": "object"}
    if annotation is str or ann_str == "str":
        return {"type": "string"}
    if annotation is int or ann_str == "int":
        return {"type": "integer"}
    if annotation is float or ann_str == "float":
        return {"type": "number"}
    if annotation is bool or ann_str == "bool":
        return {"type": "boolean"}
    if annotation is type(None) or ann_str in ("None", "NoneType"):
        return {"type": "null"}
    return {"type": "string"}


def _validate_arguments(
    arguments: dict[str, Any], schema: dict[str, Any], tool_name: str
) -> None:
    """Lightweight JSON Schema validation without external dependencies."""
    if schema.get("type") != "object":
        return
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in arguments:
            raise ToolValidationError(
                f"Tool '{tool_name}': missing required argument '{key}'"
            )
    for key, value in arguments.items():
        prop = properties.get(key)
        if prop is None:
            continue
        expected_type = prop.get("type")
        if expected_type is None:
            continue
        if not _value_matches_type(value, expected_type):
            raise ToolValidationError(
                f"Tool '{tool_name}': argument '{key}' expected type "
                f"'{expected_type}', got {type(value).__name__}"
            )


def _value_matches_type(value: Any, expected: str) -> bool:
    """Check whether *value* matches the JSON Schema *expected* type."""
    type_map: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "number": (int, float),
        "integer": (int,),
        "boolean": (bool,),
        "array": (list, tuple),
        "object": (dict,),
        "null": (type(None),),
    }
    allowed = type_map.get(expected, ())
    return isinstance(value, allowed)
