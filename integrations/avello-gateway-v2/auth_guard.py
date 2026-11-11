"""Dependency-free, fail-closed ASGI bearer guard for the Avello V2 MCP ingress."""
import hmac
import os


class ProtectedMCP:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.inner(scope, receive, send)
            return
        configured = os.getenv("AVELLO_V2_MCP_BEARER_TOKEN", "")
        supplied = [value for name, value in scope.get("headers", [])
                    if name.lower() == b"authorization"]
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
