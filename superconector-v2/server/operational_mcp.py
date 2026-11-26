"""Authenticated Superconector V2 operational MCP."""

import asyncio
import logging
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.transport_security import TransportSecuritySettings

from mcp_identity import IdentityVerifier
from host_client import call_host

audit = logging.getLogger("super-v2.audit")

mcp = FastMCP(
    "Vitrine IA Pro Superconector V2",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
    json_response=True,
    token_verifier=IdentityVerifier(),
    auth=AuthSettings(
        issuer_url=os.environ["SUPER_OIDC_ISSUER"],
        resource_server_url=os.environ["SUPER_MCP_RESOURCE"],
        required_scopes=["projects:read"],
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "super-v2.hml.vitrineiapro.com.br",
            "127.0.0.1:8000",
            "localhost:8000",
        ],
        allowed_origins=[
            "https://super-v2.hml.vitrineiapro.com.br",
        ],
    ),
)


async def run_operation(operation):
    token = get_access_token()

    if token is None:
        raise PermissionError("authentication_required")

    if "projects:read" not in token.scopes:
        raise PermissionError("scope_required")

    if token.subject != os.environ["SUPER_ALLOWED_SUBJECT"]:
        raise PermissionError("subject_not_authorized")

    if os.environ.get("SUPER_HOST_ENABLED") != "true":
        raise PermissionError("host_executor_disabled")

    try:
        result = await asyncio.to_thread(
            call_host, "superconector-v2", operation
        )
    except Exception:
        audit.warning("operation=%s status=failed", operation)
        raise RuntimeError("host_operation_failed") from None

    audit.info(
        "subject=%r operation=%s status=ok",
        token.subject, operation,
    )

    return {
        "source": "native-vps",
        **result,
    }


@mcp.tool()
async def git_status() -> dict:
    """Read the actual Superconector V2 VPS Git status."""
    return await run_operation("git_status")


@mcp.tool()
async def git_revision() -> dict:
    """Read the current VPS repository commit."""
    return await run_operation("git_revision")


@mcp.tool()
async def git_history() -> dict:
    """Read the last five repository commits."""
    return await run_operation("git_history")


@mcp.tool()
async def git_diff_check() -> dict:
    """Check the repository diff for whitespace errors."""
    return await run_operation("git_diff_check")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="streamable-http")
