from __future__ import annotations

import os
from typing import Any

import httpx

OPS_BROKER_URL = os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/")
OPS_BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
OPS_REQUEST_TIMEOUT = float(os.getenv("OPS_REQUEST_TIMEOUT", "1200"))


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {OPS_BROKER_TOKEN}"}
    with httpx.Client(timeout=OPS_REQUEST_TIMEOUT) as client:
        response = client.request(
            method,
            f"{OPS_BROKER_URL}{path}",
            headers=headers,
            json=payload,
        )
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:2000]}
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "body": body}
    return body


def project_manifest(project_id: str) -> dict[str, Any]:
    return _request("GET", f"/projects/{project_id}/manifest")


def project_workspace(project_id: str) -> dict[str, Any]:
    return _request("POST", "/projects/workspace", {"project_id": project_id})


def project_clone(project_id: str) -> dict[str, Any]:
    return _request("POST", "/projects/clone", {"project_id": project_id})


def project_status(project_id: str) -> dict[str, Any]:
    return _request("GET", f"/projects/{project_id}/status")


def project_write_file(
    project_id: str,
    path: str,
    content: str,
    backup: bool = True,
    confirm: str = "",
) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/write-file",
        {
            "project_id": project_id,
            "path": path,
            "content": content,
            "backup": backup,
            "confirm": confirm,
        },
    )


def project_php_lint(project_id: str, path: str) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/php-lint",
        {"project_id": project_id, "path": path},
    )


def project_deploy(
    project_id: str,
    environment: str = "homologation",
    update_repository: bool = True,
    build: bool = True,
    start: bool = True,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/project-deployments/deploy",
        {
            "project_id": project_id,
            "environment": environment,
            "update_repository": update_repository,
            "build": build,
            "start": start,
        },
    )
