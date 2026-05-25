"""First-class MCP (Model Context Protocol) mount for TurboAPI.

Usage::

    from turboapi import TurboAPI
    from turboapi.mcp import MCPRouter

    app = TurboAPI()
    mcp = MCPRouter(name="my-tools")

    @mcp.tool()
    def search_docs(query: str, limit: int = 10) -> list[dict]:
        '''Full-text search over the corpus.'''
        return run_query(query, limit)

    app.include_mcp(mcp, path="/mcp")
"""

import inspect
import json
import typing
from dataclasses import dataclass


@dataclass
class ToolDefinition:
    """A single MCP tool backed by a Python callable."""

    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: typing.Callable


class MCPRouter:
    """Registry of MCP tools that can be mounted on a TurboAPI app.

    Parameters
    ----------
    name:
        Human-readable server name surfaced in the MCP *initialize* response.
    version:
        Semantic version string for the MCP server info block.
    """

    def __init__(self, name: str = "turboapi-mcp", version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.tools: list[ToolDefinition] = []

    # ── decorator ────────────────────────────────────────────────────────

    def tool(
        self,
        name: str | None = None,
        description: str | None = None,
    ):
        """Register a function as an MCP tool.

        Parameters
        ----------
        name:
            Override the tool name (defaults to func.__name__).
        description:
            Override the tool description (defaults to the docstring).
        """

        def decorator(func):
            tool_name = name or func.__name__
            tool_desc = description or (func.__doc__ or "").strip()
            params = _build_json_schema(func)
            self.tools.append(
                ToolDefinition(
                    name=tool_name,
                    description=tool_desc,
                    parameters=params,
                    handler=func,
                )
            )
            return func

        return decorator

    # ── protocol helpers ─────────────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        """Return the tool definitions in MCP wire format."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.parameters,
            }
            for t in self.tools
        ]

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke a tool by *name* and return an MCP content result."""
        for t in self.tools:
            if t.name == name:
                result = t.handler(**arguments)
                # Normalize to MCP content array
                if isinstance(result, str):
                    return {"content": [{"type": "text", "text": result}]}
                elif isinstance(result, (dict, list)):
                    return {
                        "content": [
                            {"type": "text", "text": json.dumps(result, default=str)}
                        ]
                    }
                else:
                    return {"content": [{"type": "text", "text": str(result)}]}
        return {"error": {"code": -32601, "message": f"Tool not found: {name}"}}


# ── JSON Schema helpers ──────────────────────────────────────────────────────


def _python_type_to_json_schema(annotation) -> dict:
    """Map a Python type hint to a minimal JSON Schema snippet."""
    if annotation is str or annotation is inspect.Parameter.empty:
        return {"type": "string"}
    elif annotation is int:
        return {"type": "integer"}
    elif annotation is float:
        return {"type": "number"}
    elif annotation is bool:
        return {"type": "boolean"}
    elif annotation is list or (
        hasattr(annotation, "__origin__") and annotation.__origin__ is list
    ):
        return {"type": "array"}
    elif annotation is dict:
        return {"type": "object"}
    else:
        return {"type": "string"}


def _build_json_schema(func) -> dict:
    """Derive a JSON Schema *object* from a function signature."""
    sig = inspect.signature(func)
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = {}

    properties: dict[str, dict] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        annotation = hints.get(param_name, param.annotation)
        prop = _python_type_to_json_schema(annotation)
        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(param_name)
        properties[param_name] = prop

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema
