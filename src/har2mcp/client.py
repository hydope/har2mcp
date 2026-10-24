"""Minimal stdio MCP client used by `har2mcp call`. Works with mcp 1.x and 2.x."""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import StdioServerParameters


def _params(server: Path) -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=[str(server.resolve())])


@asynccontextmanager
async def _connect(server: Path):
    try:
        from mcp import Client  # mcp >= 2
    except ImportError:  # mcp 1.x
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with stdio_client(_params(server)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return
    async with Client(_params(server)) as client:
        yield client


def _schema(tool) -> dict:
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}


async def list_tools(server: Path) -> list[dict]:
    async with _connect(server) as client:
        res = await client.list_tools()
        return [{"name": t.name, "description": t.description, "schema": _schema(t)} for t in res.tools]


async def call_tool(server: Path, tool: str, arguments: dict) -> Any:
    async with _connect(server) as client:
        res = await client.call_tool(tool, arguments)
        structured = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
        if structured:
            return structured.get("result", structured) if isinstance(structured, dict) and len(structured) == 1 else structured
        texts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except ValueError:
            return joined
