"""Restricted read-only Redis PING for V5 diagnostics; no Docker exec or secrets."""
from __future__ import annotations
import socket
from typing import Any

_TARGETS = {"core": "vitrine_redis", "automation": "redis"}
_REQUEST = b"*1\r\n$4\r\nPING\r\n"
_TIMEOUT = 2.0

def redis_ping(target: str) -> dict[str, Any]:
    name = str(target)
    host = _TARGETS.get(name)
    if host is None:
        return {"ok": False, "target": name[:40], "status": "target_not_allowed"}
    try:
        with socket.create_connection((host, 6379), timeout=_TIMEOUT) as conn:
            conn.settimeout(_TIMEOUT)
            conn.sendall(_REQUEST)
            reply = conn.recv(256)
    except (OSError, TimeoutError):
        return {"ok": False, "target": name, "status": "unreachable"}
    if reply == b"+PONG\r\n":
        return {"ok": True, "target": name, "status": "healthy"}
    if reply.startswith((b"-NOAUTH ", b"-NOPERM ")):
        return {"ok": False, "target": name, "status": "authentication_required"}
    return {"ok": False, "target": name, "status": "unexpected_response"}

def install(mcp: Any) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def redis_ping_status(target: str) -> dict[str, Any]:
        """PING an allowlisted Redis alias: core or automation."""
        return redis_ping(target)
