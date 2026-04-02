"""
Minimal MCP (Model Context Protocol) server — zero external dependencies.

Implements JSON-RPC 2.0 over stdio, which is all you need for an MCP tool server.
Uses only Python standard library modules.
"""

import asyncio
import inspect
import json
import logging
import re
import sys
from typing import Any, Callable, get_type_hints

logger = logging.getLogger(__name__)

# Python type → JSON Schema type
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}

MCP_PROTOCOL_VERSION = "2024-11-05"


def _parse_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Extract description and per-parameter descriptions from a Google-style docstring."""
    if not doc:
        return "", {}

    doc = inspect.cleandoc(doc)

    # Split on section headers (Args:, Returns:, etc.)
    parts = re.split(r"\n(Args|Returns|Raises|Yields|Note|Examples?):", doc)

    # First part is the description
    description = parts[0].strip()
    description = re.sub(r"\s*\n\s*", " ", description).strip()

    # Parse the Args section if present
    param_descs: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        if parts[i] == "Args":
            current_name: str | None = None
            for line in parts[i + 1].split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                match = re.match(r"^(\w+)\s*(?:\(.*?\))?\s*:\s*(.+)", stripped)
                if match:
                    current_name = match.group(1)
                    param_descs[current_name] = match.group(2).strip()
                elif current_name:
                    param_descs[current_name] += " " + stripped
            break

    return description, param_descs


def _schema_from_function(fn: Callable) -> tuple[str, dict]:
    """Generate a JSON Schema and description from a function's signature + docstring."""
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = {}

    description, param_descs = _parse_docstring(fn.__doc__ or "")

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue

        type_hint = hints.get(name, str)
        json_type = _TYPE_MAP.get(type_hint, "string")

        prop: dict[str, Any] = {"type": json_type}

        if name in param_descs:
            prop["description"] = param_descs[name]

        if param.default is not inspect.Parameter.empty:
            default = param.default
            if isinstance(default, (str, int, float, bool)):
                prop["default"] = default
        else:
            required.append(name)

        properties[name] = prop

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required

    return description, schema


class McpServer:
    """Minimal MCP server — JSON-RPC 2.0 over stdio, no dependencies."""

    def __init__(self, name: str, version: str = "0.1.0"):
        self.name = name
        self.version = version
        self._tools: dict[str, dict[str, Any]] = {}
        self._prompts: dict[str, dict[str, Any]] = {}

    def tool(self, fn: Callable | None = None, *, name: str | None = None):
        """Register an MCP tool. Use as @server.tool() decorator."""
        def decorator(f: Callable) -> Callable:
            tool_name = name or f.__name__
            desc, schema = _schema_from_function(f)
            self._tools[tool_name] = {
                "name": tool_name,
                "description": desc,
                "handler": f,
                "inputSchema": schema,
            }
            return f

        if fn is not None:
            return decorator(fn)
        return decorator

    def prompt(self, fn: Callable | None = None, *, name: str | None = None):
        """Register an MCP prompt. Use as @server.prompt() decorator."""
        def decorator(f: Callable) -> Callable:
            prompt_name = name or f.__name__
            desc = inspect.cleandoc(f.__doc__ or "")
            desc = re.sub(r"\s*\n\s*", " ", desc).strip()
            self._prompts[prompt_name] = {
                "name": prompt_name,
                "description": desc,
                "handler": f,
            }
            return f

        if fn is not None:
            return decorator(fn)
        return decorator

    def run(self, transport: str = "stdio"):
        """Start the server. Only stdio transport is supported."""
        if transport != "stdio":
            raise ValueError(f"Only 'stdio' transport is supported, got '{transport}'")
        asyncio.run(self._run_stdio())

    async def _run_stdio(self):
        """Read JSON-RPC messages from stdin, dispatch, respond on stdout."""
        loop = asyncio.get_running_loop()

        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.buffer.readline)
            except (EOFError, OSError):
                break

            if not line:
                break

            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("Invalid JSON on stdin: %s", e)
                continue

            response = await self._dispatch(msg)
            if response is not None:
                out = json.dumps(response, separators=(",", ":")) + "\n"
                sys.stdout.buffer.write(out.encode("utf-8"))
                sys.stdout.buffer.flush()

    async def _dispatch(self, msg: dict) -> dict | None:
        """Route a JSON-RPC 2.0 message to the appropriate handler."""
        msg_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        # Notifications (no id) — no response
        if msg_id is None:
            return None

        handlers: dict[str, Callable] = {
            "initialize": self._on_initialize,
            "ping": self._on_ping,
            "tools/list": self._on_tools_list,
            "tools/call": self._on_tools_call,
            "prompts/list": self._on_prompts_list,
            "prompts/get": self._on_prompts_get,
            "resources/list": self._on_resources_list,
            "resources/templates/list": self._on_resources_list,
        }

        handler = handlers.get(method)
        if handler is None:
            return _jsonrpc_error(msg_id, -32601, f"Method not found: {method}")

        try:
            result = await handler(params)
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as e:
            logger.exception("Error handling %s", method)
            return _jsonrpc_error(msg_id, -32603, str(e))

    # ── MCP method handlers ────────────────────────────────────────

    async def _on_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}, "prompts": {}},
            "serverInfo": {"name": self.name, "version": self.version},
        }

    async def _on_ping(self, params: dict) -> dict:
        return {}

    async def _on_tools_list(self, params: dict) -> dict:
        return {
            "tools": [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["inputSchema"],
                }
                for t in self._tools.values()
            ]
        }

    async def _on_tools_call(self, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        tool = self._tools.get(name)
        if tool is None:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }

        try:
            result = tool["handler"](**arguments)
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                result = await result
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            }

    async def _on_prompts_list(self, params: dict) -> dict:
        return {
            "prompts": [
                {"name": p["name"], "description": p["description"]}
                for p in self._prompts.values()
            ]
        }

    async def _on_prompts_get(self, params: dict) -> dict:
        name = params.get("name", "")
        prompt = self._prompts.get(name)
        if prompt is None:
            raise ValueError(f"Unknown prompt: {name}")

        result = prompt["handler"]()
        if asyncio.iscoroutine(result):
            result = await result

        return {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": str(result)}}
            ]
        }

    async def _on_resources_list(self, params: dict) -> dict:
        return {"resources": []}


def _jsonrpc_error(msg_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }
