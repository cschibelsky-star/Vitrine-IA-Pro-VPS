"""HTTP MCP smoke test with exactly one FastMCP lifespan per process."""
import os
from unittest.mock import patch

from starlette.testclient import TestClient
import server


def test_mcp_http_auth_discovery_and_default_deny():
    # MCP StreamableHTTPSessionManager is intentionally single-use per app.
    with TestClient(server.app) as client:
        with patch.dict(os.environ, {"MCP_BEARER_TOKEN": "", "AVELLO_CALLS_ENABLED": "false"}):
            assert client.get("/mcp").status_code == 503

        with patch.dict(os.environ, {"MCP_BEARER_TOKEN": "a" * 48, "AVELLO_CALLS_ENABLED": "false"}):
            assert client.get("/mcp", headers={"Authorization": "Bearer incorrect"}).status_code == 401

            headers = {
                "Authorization": "Bearer " + "a" * 48,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            response = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "offline-smoke", "version": "1"},
                },
            })
            assert response.status_code == 200, response.text[:500]
            response = client.post("/mcp", headers={**headers, "MCP-Protocol-Version": "2025-03-26"}, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
            })
            assert response.status_code == 200, response.text[:500]
            found = {tool["name"] for tool in response.json()["result"]["tools"]}
            assert {"avello_status", "avello_ask"} <= found

            response = client.post("/mcp", headers={**headers, "MCP-Protocol-Version": "2025-03-26"}, json={
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "avello_ask", "arguments": {"prompt": "teste", "provider": "gpt"}},
            })
            assert response.status_code == 200, response.text[:500]
            assert "calls_disabled" in response.text
