"""Internal read-only V5 adapter. Not a public endpoint or authorization layer."""
import json
import os
import httpx

URL = "http://127.0.0.1:8867/mcp"
TOOLS = frozenset(("project_status", "project_docker_status"))
PROJECTS = frozenset(("factory",))

async def read_factory(tool: str, project: str, *, transport=None):
    if tool not in TOOLS or project not in PROJECTS:
        raise ValueError("operation_not_allowed")
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    if transport is None:
        if os.environ.get('SUPER_V5_SOCKET_ENABLED') != 'true':
            raise ValueError('private_transport_disabled')
        transport = httpx.AsyncHTTPTransport(
            uds='/run/super-v5/mcp.sock', retries=0)
        async with httpx.AsyncClient(
            transport=transport,
            timeout=20,
            trust_env=False,
            follow_redirects=False
        ) as private_client:
            response = await private_client.get(
                f"http://private/factory/{tool}")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("invalid_private_response")
            if data.get("project_id") != project:
                raise ValueError("private_identity_mismatch")
            if data.get("ok") is not True:
                raise ValueError("private_operation_failed")
            return data
    async with httpx.AsyncClient(timeout=5, trust_env=False,
                                 follow_redirects=False, transport=transport) as client:
        async def send(payload, notification=False):
            response = await client.post(URL, headers=headers, json=payload)
            response.raise_for_status()
            if notification:
                return None
            if len(response.content) > 262144:
                raise ValueError("response_too_large")
            if response.headers.get("content-type", "").startswith("text/event-stream"):
                candidates = [line[6:] for line in response.text.splitlines()
                              if line.startswith("data: ")]
                objects = [json.loads(line) for line in candidates]
                obj = next((o for o in objects if o.get("id") == payload["id"]), None)
            else:
                obj = response.json()
            if not isinstance(obj, dict) or obj.get("id") != payload["id"] or "error" in obj:
                raise ValueError("invalid_mcp_response")
            return obj["result"], response.headers
        try:
            result, meta = await send({"jsonrpc":"2.0","id":1,"method":"initialize",
                "params":{"protocolVersion":"2025-03-26","capabilities":{},
                          "clientInfo":{"name":"super-v2-read-pilot","version":"0.1"}}})
            if result.get("protocolVersion") not in ("2025-03-26","2025-06-18","2025-11-25"):
                raise ValueError("unsupported_protocol")
            headers["MCP-Protocol-Version"] = result["protocolVersion"]
            if meta.get("Mcp-Session-Id"):
                headers["Mcp-Session-Id"] = meta["Mcp-Session-Id"]
            await send({"jsonrpc":"2.0","method":"notifications/initialized"}, True)
            result, _ = await send({"jsonrpc":"2.0","id":2,"method":"tools/call",
                "params":{"name":tool,"arguments":{"project_id":project}}})
            if not isinstance(result, dict) or result.get("isError"):
                raise ValueError("upstream_tool_error")
            data = result.get("structuredContent")
            if not isinstance(data, dict):
                raise ValueError("missing_structured_content")
            if data.get("ok") is not True:
                raise ValueError("upstream_operation_failed")
            if data.get("project_id") != project:
                raise ValueError("upstream_identity_mismatch")
            return data
        finally:
            if "Mcp-Session-Id" in headers:
                try:
                    await client.delete(URL, headers=headers, timeout=2)
                except httpx.HTTPError:
                    pass
