"""Fail-closed ASGI ingress: bearer authentication and signed dispatch approval.

Approval headers are verified by dispatch_authorization.authorize inside the tool,
never trusted as an identity merely because the ingress bearer was accepted.
"""
import hmac
import os
from dispatch_request_context import RequestApproval, current_approval


def _approval_from_headers(headers):
    values = {}
    for name, value in headers:
        key = name.lower()
        if key in (b"x-via-identity", b"x-via-approval-nonce", b"x-via-approval-timestamp", b"x-via-approval-signature"):
            if key in values:
                return None
            try:
                values[key] = value.decode("ascii")
            except UnicodeDecodeError:
                return None
    if len(values) != 4:
        return None
    try:
        issued_at = int(values[b"x-via-approval-timestamp"])
    except ValueError:
        return None
    return RequestApproval(
        identity=values[b"x-via-identity"],
        nonce=values[b"x-via-approval-nonce"],
        issued_at=issued_at,
        signature=values[b"x-via-approval-signature"],
    )


class ProtectedMCP:
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
        # Headers alone do not grant permission: signature and one-time nonce
        # must be checked atomically inside the dispatch tool.
        approval = _approval_from_headers(headers)
        token = current_approval.set(approval)
        try:
            await self.inner(scope, receive, send)
        finally:
            current_approval.reset(token)
