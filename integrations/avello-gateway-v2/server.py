"""Isolated read-only MCP gateway V2. No inference, no remote execution."""
import json
import hmac
import os
import urllib.error
import urllib.request
from mcp.server.fastmcp import FastMCP

BASE_URL = "https://avellogateway.online"
MAX_BYTES = 1024 * 1024
mcp = FastMCP("Vitrine Avello Gateway V2", stateless_http=True, json_response=True)

@mcp.tool()
def gateway_status() -> dict:
    """Read configuration readiness without exposing any credential."""
    return {"service": "vitrine-avello-gateway-v2", "mode": "read_only",
            "gateway_key_present": bool(os.getenv("AVELLO_V2_API_KEY")),
            "inference_enabled": False, "remote_execution": False}

@mcp.tool()
def gateway_models() -> dict:
    """GET fixed model catalog, never inference; no redirects or secret disclosure."""
    key = os.getenv("AVELLO_V2_API_KEY", "")
    if not key:
        return {"status": "not_configured"}
    request = urllib.request.Request(
        BASE_URL + "/v1/models",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=12) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {"status": "invalid_response", "reason": "too_large"}
        payload = json.loads(raw)
        records = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            return {"status": "invalid_response"}
        models = sorted({r["id"] for r in records if isinstance(r, dict)
                         and isinstance(r.get("id"), str)
                         and 0 < len(r["id"]) <= 100
                         and all(c.isascii() and (c.isalnum() or c in "-._:/") for c in r["id"])})
        return {"status": "ok", "models": models[:200]}
    except urllib.error.HTTPError as exc:
        return {"status": "provider_error", "http_status": exc.code}
    except (urllib.error.URLError, TimeoutError):
        return {"status": "network_error"}
    except (ValueError, TypeError):
        return {"status": "invalid_response"}

class ProtectedMCP:
    """Fail-closed bearer authorization for every HTTP request and websocket."""
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.inner(scope, receive, send)
            return
        configured = os.getenv("AVELLO_V2_MCP_BEARER_TOKEN", "")
        headers = scope.get("headers", [])
        supplied = [value for name, value in headers if name.lower() == b"authorization"]
        expected = ("Bearer " + configured).encode("utf-8")
        authorized = bool(configured) and len(supplied) == 1 and hmac.compare_digest(supplied[0], expected)
        if not authorized:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
            return
        await self.inner(scope, receive, send)

app = ProtectedMCP(mcp.streamable_http_app())
