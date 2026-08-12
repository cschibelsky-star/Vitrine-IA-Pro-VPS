from __future__ import annotations

import os
from typing import Any

import httpx

OPS_BROKER_URL = os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/")
OPS_BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
OPS_REQUEST_TIMEOUT = float(os.getenv("OPS_REQUEST_TIMEOUT", "1200"))


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if OPS_BROKER_TOKEN:
        headers["Authorization"] = f"Bearer {OPS_BROKER_TOKEN}"
    return headers


def _request(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
    """Cliente interno do ops_broker; não registra ferramentas MCP.

    O registry MCP é único e pertence ao main.py do conector. Manter este
    módulo livre de FastMCP evita divergência entre catálogo e execução.
    """
    try:
        with httpx.Client(timeout=timeout or OPS_REQUEST_TIMEOUT) as client:
            response = client.request(
                method,
                f"{OPS_BROKER_URL}{path}",
                headers=_headers(),
                json=payload if payload is not None else None,
            )
    except httpx.TimeoutException as exc:
        return {"ok": False, "error": "ops_broker_timeout", "detail": str(exc), "path": path}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": "ops_broker_unreachable", "detail": str(exc), "path": path}

    try:
        body: Any = response.json()
    except ValueError:
        body = {"detail": response.text[:2000]}

    if response.status_code >= 400:
        return {
            "ok": False,
            "error": "ops_broker_http_error",
            "status_code": response.status_code,
            "body": body,
            "path": path,
        }
    return body if isinstance(body, dict) else {"ok": True, "data": body}


def _post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _request("POST", path, payload)


def tvsumare_health() -> dict[str, Any]:
    return _request("GET", "/tvsumare/health", timeout=30)


def tvsumare_workspace_create() -> dict[str, Any]:
    return _post("/tvsumare/workspace/create")


def tvsumare_write_file(path: str, content: str, backup: bool = True) -> dict[str, Any]:
    return _post("/tvsumare/write", {"path": path, "content": content, "backup": backup})


def tvsumare_git_status() -> dict[str, Any]:
    return _post("/tvsumare/git/status")


def tvsumare_php_lint() -> dict[str, Any]:
    return _post("/tvsumare/tests/php-lint")


def tvsumare_docker_build() -> dict[str, Any]:
    return _post("/tvsumare/docker/build")


def tvsumare_docker_up() -> dict[str, Any]:
    return _post("/tvsumare/docker/up")


def tvsumare_create_homologation_vhost(
    domain: str = "tv-hml.vitrineiapro.com.br",
    upstream: str = "tvsumare_web:80",
) -> dict[str, Any]:
    return _post(
        "/tvsumare/nginx/vhost",
        {"domain": domain, "upstream": upstream, "homologation": True},
    )


def tvsumare_create_release_zip() -> dict[str, Any]:
    return _post("/tvsumare/release/zip")
