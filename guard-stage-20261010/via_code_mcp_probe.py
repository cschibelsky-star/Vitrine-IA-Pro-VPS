"""Health probe for the *running* isolated FastMCP endpoint. No paid inference."""
from __future__ import annotations
import asyncio
import sys
from fastmcp import Client

async def check() -> int:
    async with Client("http://127.0.0.1:8000/mcp") as client:
        listed = await client.list_tools()
        names = [tool.name for tool in listed]
        return 0 if names.count("project_roteia_via_code_pilot_execute") == 1 else 2

if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(check(), timeout=8)))
    except Exception:
        sys.exit(3)
