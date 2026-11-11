"""Public, non-privileged MCP entry point for Superconector V2.

Operational tools require a separately reviewed, OAuth-protected tenant gateway.
No VPS, Docker, filesystem, or tenant credentials are exposed here.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Vitrine IA Pro Superconector V2", host="0.0.0.0", port=8000, stateless_http=True, json_response=True)

PUBLIC_FEATURES = (
    "Lista de capacidades e integracoes suportadas",
    "Orientacoes de conexao para clientes autorizados",
    "Estado de disponibilidade de funcoes publicas",
)

@mcp.tool()
def public_capabilities() -> dict:
    """List safe public features without exposing internal infrastructure."""
    return {
        "product": "Vitrine IA Pro — Superconector V2",
        "release": "0.2.0-dev",
        "features": list(PUBLIC_FEATURES),
        "operational_access": "not_exposed",
        "multi_tenant_authorization": "pending_implementation",
    }

@mcp.tool()
def connection_requirements() -> dict:
    """Explain access requirements; never request secrets in chat."""
    return {
        "public_discovery": True,
        "operations_require": [
            "verified OAuth user identity",
            "tenant binding validated server-side",
            "explicit role and scope authorization",
            "per-action approval and audit for mutating operations",
        ],
        "connection_status": "public_information_only",
        "credential_handling": "Use supported authenticated connection flow; never paste secrets in chat.",
    }

@mcp.tool()
def service_readiness() -> dict:
    """Report readiness of the informational layer, not an operational service."""
    return {
        "service": "public-mcp",
        "status": "available",
        "vps_inspection": "not_available",
        "deploy_operations": "not_available",
        "production_operations": "not_available",
    }

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
