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
