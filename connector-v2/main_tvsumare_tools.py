from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("TV Sumaré Operations")

OPS_BROKER_URL = os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/")
OPS_BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
OPS_REQUEST_TIMEOUT = float(os.getenv("OPS_REQUEST_TIMEOUT", "1200"))


def _post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {OPS_BROKER_TOKEN}"}
    with httpx.Client(timeout=OPS_REQUEST_TIMEOUT) as client:
        response = client.post(
            f"{OPS_BROKER_URL}{path}",
            headers=headers,
            json=payload or {},
        )
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:2000]}
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "body": body}
    return body


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def tvsumare_health() -> dict[str, Any]:
    """Verifica se o módulo operacional da TV Sumaré está ativo na VPS."""
    headers = {"Authorization": f"Bearer {OPS_BROKER_TOKEN}"}
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{OPS_BROKER_URL}/tvsumare/health", headers=headers)
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:2000]}
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "body": body}
    return body


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_workspace_create() -> dict[str, Any]:
    """Cria a estrutura controlada /srv/tvsumare e /srv/backups/tvsumare."""
    return _post("/tvsumare/workspace/create")


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_write_file(path: str, content: str, backup: bool = True) -> dict[str, Any]:
    """Grava arquivo textual no workspace da TV Sumaré com backup opcional."""
    return _post("/tvsumare/write", {"path": path, "content": content, "backup": backup})


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def tvsumare_git_status() -> dict[str, Any]:
    """Retorna o git status do repositório da TV Sumaré na VPS."""
    return _post("/tvsumare/git/status")


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def tvsumare_php_lint() -> dict[str, Any]:
    """Executa lint PHP em todos os arquivos versionados da TV Sumaré."""
    return _post("/tvsumare/tests/php-lint")


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_docker_build() -> dict[str, Any]:
    """Constrói os containers de homologação da TV Sumaré."""
    return _post("/tvsumare/docker/build")


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_docker_up() -> dict[str, Any]:
    """Inicializa ou atualiza os containers de homologação da TV Sumaré."""
    return _post("/tvsumare/docker/up")


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_create_homologation_vhost(
    domain: str = "tv-hml.vitrineiapro.com.br",
    upstream: str = "tvsumare_web:80",
) -> dict[str, Any]:
    """Cria e valida o virtual host de homologação e recarrega o Nginx após nginx -t."""
    return _post(
        "/tvsumare/nginx/vhost",
        {"domain": domain, "upstream": upstream, "homologation": True},
    )


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_create_release_zip() -> dict[str, Any]:
    """Gera um ZIP versionado sem segredos, uploads, dados, logs ou dependências locais."""
    return _post("/tvsumare/release/zip")
