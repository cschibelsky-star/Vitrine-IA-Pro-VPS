"""Authenticated Superconector V2 operational MCP."""

import asyncio
import logging
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.transport_security import TransportSecuritySettings

from mcp_identity import IdentityVerifier
from host_client import call_host
from maintenance_client import authorize, call_maintenance

audit = logging.getLogger("super-v2.audit")

class OperationalMCP(FastMCP):
    def streamable_http_app(self):
        app = super().streamable_http_app()
        auth = self.settings.auth
        metadata_routes = create_protected_resource_routes(
            resource_url=auth.resource_server_url,
            authorization_servers=[auth.issuer_url],
            scopes_supported=["projects:read", "projects:write"],
        )
        for metadata_route in metadata_routes:
            matches = [
                i for i, route in enumerate(app.router.routes)
                if getattr(route, "path", None) == metadata_route.path
            ]
            if len(matches) != 1:
                raise RuntimeError("unexpected OAuth metadata route count")
            app.router.routes[matches[0]] = metadata_route
        return app


mcp = OperationalMCP(
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


async def run_maintenance(operation, confirm="", project_id=None, commit=None):
    token = get_access_token()
    authorize(token, operation, os.environ["SUPER_ALLOWED_SUBJECT"],
              os.environ.get("SUPER_MAINTENANCE_ENABLED") == "true", confirm)
    try:
        result = await asyncio.to_thread(call_maintenance, operation, project_id, commit)
    except Exception:
        audit.warning("maintenance=%s status=failed", operation)
        raise RuntimeError("maintenance_failed") from None
    audit.info("subject=%r maintenance=%s project=%r status=ok", token.subject, operation, project_id)
    return {"source": "native-vps", **result}


@mcp.tool()
async def candidate_status() -> dict:
    """Read the isolated HML candidate container status."""
    return await run_maintenance("candidate_status")


@mcp.tool()
async def candidate_restart(confirm: str) -> dict:
    """Restart only the isolated HML candidate; requires projects:write and explicit EXECUTAR confirmation."""
    return await run_maintenance("candidate_restart", confirm)


@mcp.tool()
async def assessor_hml_snapshot(confirm: str) -> dict:
    """Create and verify a private snapshot of the five Assessor Online HML files."""
    return await run_maintenance("assessor_hml_snapshot", confirm)


@mcp.tool()
async def hml_project_catalog() -> dict:
    """List registered HML projects and the operations their broker supports."""
    return await run_maintenance("hml_project_catalog")


@mcp.tool()
async def project_hml_snapshot(project_id: str, confirm: str) -> dict:
    """Save and verify the registered files of an allowlisted HML project."""
    return await run_maintenance("project_hml_snapshot", confirm, project_id)


@mcp.tool()
async def project_hml_database_backup(project_id: str, confirm: str) -> dict:
    """Create and validate an online SQLite backup for the supported HML project."""
    return await run_maintenance("project_hml_database_backup", confirm, project_id)


@mcp.tool()
async def project_hml_release_preflight(project_id: str, commit: str) -> dict:
    """Read the requested Git revision and current image identities for one HML project."""
    return await run_maintenance("project_hml_release_preflight", project_id=project_id, commit=commit)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="streamable-http")
