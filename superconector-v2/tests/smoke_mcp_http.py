"""Isolated smoke: actual MCP initialize, list_tools and calls, no tenant secrets."""
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:8878/mcp"

async def main():
    async with streamablehttp_client(URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            tools = await client.list_tools()
            expected = {"public_capabilities", "connection_requirements", "service_readiness"}
            names = {tool.name for tool in tools.tools}
            assert names == expected, f"unexpected MCP tools: {sorted(names)}"
            for name in sorted(expected):
                result = await client.call_tool(name, arguments={})
                assert not result.isError, f"call_tool failed for {name}: {result}"
                body = result.structuredContent or {}
                assert isinstance(body, dict)
                assert body.get("production_operations") == "not_available" if name == "service_readiness" else True
            print(f"V2 MCP initialize + tools/list + tools/call: PASS ({len(names)} tools)")

if __name__ == "__main__":
    asyncio.run(main())
