"""Isolated PR smoke: exercise MCP over HTTP without mounting infrastructure."""
from __future__ import annotations

import asyncio
import os
from fastmcp import Client

URL = os.environ.get("V5_SMOKE_URL", "http://127.0.0.1:8000/mcp")


async def main() -> None:
    async with Client(URL, timeout=8) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        required = {
            "connector_health",
            "project_compose_service_execute",
            "project_compose_service_status",
        }
        missing = required - names
        assert not missing, f"MCP tools missing: {sorted(missing)}"
        result = await client.call_tool("connector_health", {})
        assert not result.is_error, "connector_health returned MCP error"
        print("MCP initialize + tools/list + connector_health: PASS")
        print(f"Tool count: {len(names)}")


if __name__ == "__main__":
    asyncio.run(main())
