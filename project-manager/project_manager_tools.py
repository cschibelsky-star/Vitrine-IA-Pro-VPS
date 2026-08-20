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


def project_docker_container_info(project_id: str, container_name: str) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/docker/container-info",
        {"project_id": project_id, "container_name": container_name},
    )


def project_docker_container_env_safe(project_id: str, container_name: str) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/docker/container-env-safe",
        {"project_id": project_id, "container_name": container_name},
    )


def project_container_exec(
    project_id: str,
    container_name: str,
    command: list[str],
    workdir: str = "/var/www/html",
    confirm: str = "",
) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/docker/container-exec",
        {
            "project_id": project_id,
            "container_name": container_name,
            "command": command,
            "workdir": workdir,
            "confirm": confirm,
        },
    )


def project_http_check(project_id: str, url: str, method: str = "GET") -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/http-check",
        {"project_id": project_id, "url": url, "method": method},
    )


def project_port_check(project_id: str, host: str, port: int) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/port-check",
        {"project_id": project_id, "host": host, "port": port},
    )


def project_compose_explicit(
    project_id: str,
    compose_file: str,
    action: str = "status",
    docker_project: str = "",
    confirm: str = "",
) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/compose-explicit",
        {
            "project_id": project_id,
            "compose_file": compose_file,
            "action": action,
            "docker_project": docker_project,
            "confirm": confirm,
        },
    )


def project_file_read_safe(project_id: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/file-read-safe",
        {"project_id": project_id, "path": path, "max_bytes": max_bytes},
    )


def project_file_patch_text(
    project_id: str,
    path: str,
    old: str,
    new: str,
    confirm: str = "",
) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/file-patch-text",
        {"project_id": project_id, "path": path, "old": old, "new": new, "confirm": confirm},
    )


def project_manifest_repository_update(
    project_id: str,
    url: str,
    branch: str,
    confirm: str = "",
) -> dict[str, Any]:
    return _request(
        "POST",
        "/projects/manifest/repository-update",
        {"project_id": project_id, "url": url, "branch": branch, "confirm": confirm},
    )
