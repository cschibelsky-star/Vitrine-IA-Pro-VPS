"""Metadata-only FastMCP tool catalogue. Never invokes a tool or prints secrets."""
from __future__ import annotations
import asyncio
import json
import sys
from fastmcp import Client

ALLOWED = {
    "http://127.0.0.1:8000/mcp",
    "http://vitrine_mcp_v5:8000/mcp",
}

async def main(url: str) -> None:
    if url not in ALLOWED:
        raise ValueError("MCP endpoint not allowlisted")
    async with Client(url) as client:
        tools = await client.list_tools()
    names = sorted(t.name for t in tools)
    if len(names) != len(set(names)) or len(names) < 20:
        raise ValueError("unexpected MCP catalog size or duplicate")
    print(json.dumps(names, separators=(",", ":")))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(2)
    asyncio.run(asyncio.wait_for(main(sys.argv[1]), timeout=12))
