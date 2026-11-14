"""Authenticated request context for MCP tool calls.

The ingress guard verifies bearer authentication before assigning this context.
Never accept caller identity or approval fields as MCP tool arguments.
"""
from contextvars import ContextVar
from dataclasses import dataclass

@dataclass(frozen=True)
class RequestApproval:
    identity: str
    nonce: str
    issued_at: int
    signature: str

current_approval: ContextVar[RequestApproval | None] = ContextVar("via_current_approval", default=None)
